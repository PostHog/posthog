import json
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.ai_observability.backend.composite_formula import CompositeFormula
from products.ai_observability.backend.composite_scorers import CompositeScorers
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineDeletedIdentity,
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
    PayloadState,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition
from products.ai_observability.backend.offline_evaluation_service import (
    OfflineEvaluationConflict,
    OfflineEvaluationNotFound,
    OfflineEvaluationValidationError,
    OfflineResultBuilder,
    ResultIdentity,
    _experiment_counts,
    _locked_experiment,
)
from products.ai_observability.backend.offline_evaluation_types import (
    MAX_ITEM_PAYLOAD_BYTES,
    MAX_RESULT_PAYLOAD_BYTES,
    JSONValue,
    ResultStatus,
    ResultSubmission,
    ResultValue,
)

type Target = Literal["item", "result", "item_payload", "result_payload"]
type Owner = OfflineExperimentItem | OfflineEvaluationResult


def _save_score(result: OfflineEvaluationResult, computed: OfflineEvaluationResult, scored_at: datetime) -> None:
    if result.status == "error" and computed.status != "error":
        payload = (
            OfflineEvaluationResultPayload.objects.for_team(result.team_id)
            .filter(result=result, data__has_key="error_message")
            .first()
        )
        if payload is not None:
            del payload.data["error_message"]
            payload.save(update_fields=["data"])
    if result.original_status is None:
        result.original_status = result.status
        result.original_error_code = result.error_code
    result.status = computed.status
    result.error_code = computed.error_code
    result.boolean_value = computed.boolean_value
    result.numeric_value = computed.numeric_value
    result.categorical_values = computed.categorical_values
    result.score_updated_at = scored_at
    result.revision += 1
    result.save(
        update_fields=[
            "original_status",
            "original_error_code",
            "status",
            "error_code",
            "boolean_value",
            "numeric_value",
            "categorical_values",
            "score_updated_at",
            "revision",
        ]
    )


def _update_score(
    result: OfflineEvaluationResult,
    dependents: QuerySet[OfflineEvaluationResult],
    changes: dict[str, JSONValue],
    now: datetime,
) -> None:
    if result.input_result_ids is not None:
        raise OfflineEvaluationValidationError("value", "Update a reported input to change this composite score.")
    status = cast(ResultStatus, changes.get("status", result.status))
    value = changes.get("value", result.value if status == "ok" else None)
    error_code = changes.get("error_code", result.error_code if status == "error" else None)
    if (status == "ok") != (value is not None):
        raise OfflineEvaluationValidationError("value", "Supply a value only for a successful result.")
    if status != "error" and error_code is not None:
        raise OfflineEvaluationValidationError("error_code", "Supply an error code only for an error result.")
    builder = OfflineResultBuilder(result.team_id)
    submission = ResultSubmission(
        item_id=result.item_id,
        scorer_version_id=result.scorer_version_id,
        status=status,
        value=cast(ResultValue | None, value),
        error_code=cast(str | None, error_code),
    )
    updated = builder.reported(
        submission,
        version=result.scorer_version,
        fingerprint=result.submission_fingerprint,
        accepted_at=result.accepted_at,
        index=None,
    )
    _save_score(result, updated, now)
    composites = list(
        dependents.select_related("scorer_version__definition").select_for_update(of=("self",)).order_by("id")
    )
    if not composites:
        return
    sources = {
        ResultIdentity(item_id=row.item_id, scorer_version_id=row.scorer_version_id): row
        for row in OfflineEvaluationResult.objects.for_team(result.team_id)
        .filter(item_id=result.item_id, id__in={pk for row in composites for pk in (row.input_result_ids or [])})
        .select_related("scorer_definition")
    }
    for row in composites:
        version = row.scorer_version
        assert version.composition is not None
        kinds = {
            source["alias"]: sources[
                ResultIdentity(item_id=row.item_id, scorer_version_id=UUID(source["scorer_version_id"]))
            ].scorer_definition.kind
            for source in version.composition["inputs"]
        }
        computed = builder.composite(
            ResultSubmission(item_id=row.item_id, scorer_version_id=version.id, status="ok", calculate=True),
            version=version,
            formula=CompositeFormula.parse(version.composition["expression"], kinds, version.definition.kind),
            results=sources,
            fingerprint=row.submission_fingerprint,
            accepted_at=row.accepted_at,
            index=0,
        )
        _save_score(row, computed, computed.score_updated_at or now)


def _write_payload(owner: Owner, *, patch: dict[str, JSONValue] | None, now: datetime) -> None:
    rows: QuerySet[OfflineExperimentItemPayload] | QuerySet[OfflineEvaluationResultPayload]
    if isinstance(owner, OfflineExperimentItem):
        rows = OfflineExperimentItemPayload.objects.for_team(owner.team_id)
        max_bytes = MAX_ITEM_PAYLOAD_BYTES
    else:
        rows = OfflineEvaluationResultPayload.objects.for_team(owner.team_id)
        max_bytes = MAX_RESULT_PAYLOAD_BYTES
    deadline = owner.accepted_at + timedelta(days=30)
    fields = ["revision", "payload_state", "payload_expires_at"]
    if patch is None:
        rows.filter(pk=owner.pk).delete()
        owner.payload_deleted_at = now
        owner.payload_state = PayloadState.EXPIRED
        fields.append("payload_deleted_at")
    else:
        if now >= deadline or owner.payload_state == PayloadState.EXPIRED:
            raise OfflineEvaluationConflict(
                "payload_unavailable", "This payload was deleted or its 30-day window has ended."
            )
        existing = rows.filter(pk=owner.pk).values_list("data", flat=True).first() or {}
        merged = {**existing, **patch}
        if len(json.dumps(merged, ensure_ascii=False, separators=(",", ":")).encode()) > max_bytes:
            raise OfflineEvaluationValidationError("payload", f"The updated payload must fit within {max_bytes} bytes.")
        if (
            isinstance(owner, OfflineEvaluationResult)
            and owner.status != "error"
            and merged.get("error_message") is not None
        ):
            raise OfflineEvaluationValidationError("payload", "Only an error result may have an error message.")
        rows.update_or_create(pk=owner.pk, defaults={"team_id": owner.team_id, "data": merged})
        owner.payload_state = PayloadState.AVAILABLE
        if isinstance(owner, OfflineExperimentItem) and any(
            key in patch
            and (
                key not in existing
                or json.dumps(patch[key], sort_keys=True) != json.dumps(existing[key], sort_keys=True)
            )
            for key in ("input", "output", "expected_output")
        ):
            owner.content_updated_at = now
            fields.append("content_updated_at")
    owner.payload_expires_at = deadline
    owner.revision += 1
    owner.save(update_fields=fields)


def _delete_resource(experiment: OfflineExperiment, owner: Owner, affected: QuerySet[OfflineEvaluationResult]) -> None:
    if experiment.status == OfflineExperiment.Status.UPLOADING:
        if isinstance(owner, OfflineExperimentItem):
            OfflineDeletedIdentity.objects.for_team(experiment.team_id).filter(
                experiment=experiment, item_id=owner.id
            ).delete()
            OfflineDeletedIdentity.objects.for_team(experiment.team_id).create(
                team_id=experiment.team_id, experiment=experiment, item_id=owner.id
            )
        else:
            OfflineDeletedIdentity.objects.for_team(experiment.team_id).bulk_create(
                [
                    OfflineDeletedIdentity(
                        team_id=experiment.team_id, experiment=experiment, item_id=item_id, scorer_version_id=version_id
                    )
                    for item_id, version_id in affected.values_list("item_id", "scorer_version_id")
                ]
            )
    elif experiment.closed_item_count is None:
        counts = _experiment_counts(experiment)
        experiment.closed_item_count = counts.accepted_item_count
        experiment.closed_result_count = counts.accepted_result_count
        experiment.save(update_fields=["closed_item_count", "closed_result_count"])
    if isinstance(owner, OfflineExperimentItem):
        owner.delete()
    else:
        affected.delete()


@transaction.atomic
def mutate_offline_evaluation(
    *,
    team_id: int,
    experiment_id: UUID,
    resource_id: UUID,
    target: Target,
    expected_revision: int,
    changes: dict[str, JSONValue] | None,
    access: UserAccessControl,
) -> int:
    experiment = _locked_experiment(team_id=team_id, experiment_id=experiment_id)
    results = OfflineEvaluationResult.objects.for_team(team_id).filter(item__experiment_id=experiment_id)
    owner: Owner | None
    if target in ("item", "item_payload"):
        owner = (
            OfflineExperimentItem.objects.for_team(team_id)
            .select_for_update()
            .filter(experiment=experiment, id=resource_id)
            .first()
        )
    else:
        owner = (
            results.select_related("scorer_version__definition")
            .select_for_update(of=("self",))
            .filter(id=resource_id)
            .first()
        )
    if owner is None:
        raise OfflineEvaluationNotFound
    affected = results.none()
    dependents = results.none()
    if isinstance(owner, OfflineEvaluationResult):
        affected = results.filter(id=owner.id)
        if target == "result":
            dependents = results.filter(item_id=owner.item_id, input_result_ids__contains=[owner.id])
            affected = results.filter(Q(id=owner.id) | Q(id__in=dependents.values("id")))
    elif target == "item" and changes is None:
        affected = results.filter(item_id=owner.id)
    if isinstance(owner, OfflineEvaluationResult) or (target == "item" and changes is None):
        definitions = access.filter_queryset_by_access_level(
            ScoreDefinition.objects.filter(team_id=team_id), include_all_if_admin=True, resource="llm_analytics"
        )
        if affected.exclude(
            scorer_version__in=CompositeScorers.accessible_versions(definitions, team_id=team_id)
        ).exists():
            raise OfflineEvaluationNotFound
    if owner.revision != expected_revision:
        raise OfflineEvaluationConflict(
            "revision_conflict", "This resource changed. Read its latest revision and try again."
        )
    now = timezone.now()
    if target in ("item_payload", "result_payload"):
        _write_payload(
            owner, patch=cast(dict[str, JSONValue], changes["payload"]) if changes is not None else None, now=now
        )
    elif changes is None:
        _delete_resource(experiment, owner, affected)
    elif isinstance(owner, OfflineEvaluationResult):
        _update_score(owner, dependents, changes, now)
    else:
        for name in ("case_key", "trial", "application_trace_id", "model_version"):
            if name in changes:
                setattr(owner, name, changes[name])
        owner.revision += 1
        owner.save(update_fields=[*changes, "revision"])
    experiment.updated_at = now
    experiment.save(update_fields=["updated_at"])
    return owner.revision
