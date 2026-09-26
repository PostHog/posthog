from __future__ import annotations

from dataclasses import (
    asdict,
    fields as dataclass_fields,
)
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, NoReturn
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen

from products.ai_observability.backend.dataset_queries import dataset_item_versions_at_revision
from products.ai_observability.backend.models.datasets import Dataset, DatasetItemVersion, DatasetRevision
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
    PayloadState,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition, ScoreDefinitionVersion
from products.ai_observability.backend.offline_evaluation_fingerprint import submission_fingerprint
from products.ai_observability.backend.offline_evaluation_types import (
    ExperimentSubmission,
    ItemSubmission,
    ResultSubmission,
    UploadSubmission,
)
from products.ai_observability.backend.score_validation import validate_score_value

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from products.access_control.backend.facade.user_access_control import UserAccessControl


@frozen
class ExperimentCounts:
    accepted_item_count: int
    accepted_result_count: int
    expected_item_count: int | None
    expected_result_count: int | None


@frozen
class ExperimentReceipt:
    experiment: OfflineExperiment
    counts: ExperimentCounts
    created: bool = False


@frozen
class ItemReceipt:
    id: UUID
    accepted_at: datetime
    created: bool


@frozen
class ResultIdentity:
    item_id: UUID
    scorer_version_id: UUID


@frozen
class ResultReceipt:
    id: UUID
    item_id: UUID
    scorer_version_id: UUID
    accepted_at: datetime
    created: bool


@frozen
class UploadReceipt:
    items: list[ItemReceipt]
    results: list[ResultReceipt]


class OfflineEvaluationValidationError(Exception):
    def __init__(self, field: str, detail: str, *, errors: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.field = field
        self.detail = detail
        self.errors = errors if errors is not None else {field: detail}

    @classmethod
    def from_errors(cls, errors: dict[str, str]) -> OfflineEvaluationValidationError:
        field = next(iter(errors))
        return cls(field, errors[field], errors=errors)


class OfflineEvaluationNotFound(Exception):
    pass


class OfflineEvaluationConflict(Exception):
    def __init__(
        self, code: str, detail: str, *, field: str | None = None, counts: ExperimentCounts | None = None
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.field = field
        self.counts = counts


def _raise_integrity_conflict(error: IntegrityError) -> NoReturn:
    constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
    if constraint in {"llm_analytics_offlineexperiment_pkey", "llm_analytics_offlineexperimentitem_pkey"}:
        raise OfflineEvaluationConflict("identity_conflict", "This UUID cannot be used for this submission.") from error
    if constraint in {
        "aio_offline_exp_dataset_owner_fk",
        "aio_offline_item_dataset_owner_fk",
        "aio_offline_result_scorer_owner_fk",
        "aio_offline_result_scorer_version_fk",
    }:
        raise OfflineEvaluationConflict(
            "reference_conflict", "A referenced resource changed during the upload. Check its ID and retry."
        ) from error
    raise error


def _check_fingerprint(actual: str, expected: str, *, field: str) -> None:
    if actual != expected:
        raise OfflineEvaluationConflict(
            "content_conflict", "This identity was already accepted with different content.", field=field
        )


def _provenance_identifier(submitted: str | None, derived: str, *, field: str) -> str:
    if submitted is not None and submitted != derived:
        raise OfflineEvaluationValidationError(field, "This identifier does not match the linked PostHog dataset.")
    return derived


def _experiment_counts(experiment: OfflineExperiment) -> ExperimentCounts:
    return ExperimentCounts(
        accepted_item_count=OfflineExperimentItem.objects.for_team(experiment.team_id)
        .filter(experiment_id=experiment.id)
        .count(),
        accepted_result_count=OfflineEvaluationResult.objects.for_team(experiment.team_id)
        .filter(item__experiment_id=experiment.id)
        .count(),
        expected_item_count=experiment.expected_item_count,
        expected_result_count=experiment.expected_result_count,
    )


def _locked_experiment(*, team_id: int, experiment_id: UUID) -> OfflineExperiment:
    experiment = OfflineExperiment.objects.for_team(team_id).select_for_update().filter(id=experiment_id).first()
    if experiment is None:
        raise OfflineEvaluationNotFound
    return experiment


class _OfflineEvaluationService:
    def __init__(self, *, team_id: int, user_access_control: UserAccessControl | None) -> None:
        self.team_id = team_id
        self._user_access_control = user_access_control

    def _dataset_revisions(self) -> QuerySet[DatasetRevision]:
        revisions = DatasetRevision.objects.for_team(self.team_id, canonical=True)
        if self._user_access_control is not None:
            datasets = self._user_access_control.filter_queryset_by_access_level(
                Dataset.objects.for_team(self.team_id, canonical=True), include_all_if_admin=True, resource="dataset"
            )
            revisions = revisions.filter(dataset_id__in=datasets.values("id"))
        return revisions

    def _scorer_versions(self) -> QuerySet[ScoreDefinitionVersion]:
        definitions = ScoreDefinition.objects.filter(team_id=self.team_id)
        if self._user_access_control is not None:
            definitions = self._user_access_control.filter_queryset_by_access_level(
                definitions, include_all_if_admin=True, resource="llm_analytics"
            )
        # nosemgrep: idor-lookup-without-user -- Versions inherit team and caller access from their definitions.
        return ScoreDefinitionVersion.objects.filter(definition__in=definitions)


class OfflineExperimentService(_OfflineEvaluationService):
    def _creation_fields(self, submission: ExperimentSubmission) -> dict[str, object]:
        fields: dict[str, object] = asdict(submission)
        if submission.dataset_revision_id is None:
            if submission.dataset_source == "posthog":
                raise OfflineEvaluationValidationError("dataset_revision_id", "Select a PostHog dataset revision.")
            return fields
        revision = self._dataset_revisions().filter(id=submission.dataset_revision_id).first()
        if revision is None:
            raise OfflineEvaluationValidationError("dataset_revision_id", "Select an existing dataset revision.")
        errors: dict[str, str] = {}
        for field, derived in {
            "dataset_source": "posthog",
            "dataset_identifier": str(revision.dataset_id),
            "dataset_revision_identifier": str(revision.id),
        }.items():
            try:
                fields[field] = _provenance_identifier(getattr(submission, field), derived, field=field)
            except OfflineEvaluationValidationError as error:
                errors.update(error.errors)
        if errors:
            raise OfflineEvaluationValidationError.from_errors(errors)
        return fields

    def create(self, submission: ExperimentSubmission) -> ExperimentReceipt:
        fingerprint = submission_fingerprint(submission)
        try:
            with transaction.atomic():
                experiments = OfflineExperiment.objects.for_team(self.team_id).select_for_update()
                existing = experiments.filter(id=submission.id).first()
                if existing is not None:
                    _check_fingerprint(existing.submission_fingerprint, fingerprint, field="id")
                    return ExperimentReceipt(experiment=existing, counts=_experiment_counts(existing))
                fields = self._creation_fields(submission)
                fields.pop("id")
                experiment, created = experiments.get_or_create(
                    id=submission.id,
                    defaults={**fields, "team_id": self.team_id, "submission_fingerprint": fingerprint},
                )
                _check_fingerprint(experiment.submission_fingerprint, fingerprint, field="id")
                receipt = ExperimentReceipt(
                    experiment=experiment, counts=_experiment_counts(experiment), created=created
                )
        except IntegrityError as error:
            _raise_integrity_conflict(error)
        return receipt

    def close(self, experiment_id: UUID, *, status: Literal["completed", "failed"]) -> ExperimentReceipt:
        with transaction.atomic():
            experiment = _locked_experiment(team_id=self.team_id, experiment_id=experiment_id)
            counts = _experiment_counts(experiment)
            if experiment.status == status:
                return ExperimentReceipt(experiment=experiment, counts=counts)
            if experiment.status != OfflineExperiment.Status.UPLOADING:
                raise OfflineEvaluationConflict("experiment_closed", "This experiment is already closed.")
            if status == "completed" and (
                counts.expected_item_count is not None
                and counts.expected_item_count != counts.accepted_item_count
                or counts.expected_result_count is not None
                and counts.expected_result_count != counts.accepted_result_count
            ):
                raise OfflineEvaluationConflict(
                    "expected_count_mismatch",
                    "Accepted counts do not match the experiment's expected counts.",
                    counts=counts,
                )
            experiment.status = status
            experiment.finished_at = timezone.now()
            experiment.save(update_fields=["status", "finished_at"])
            receipt = ExperimentReceipt(experiment=experiment, counts=counts)
        return receipt


class OfflineEvaluationIngestionService(_OfflineEvaluationService):
    def _existing_results(
        self, *, experiment_id: UUID, submissions: list[ResultSubmission]
    ) -> dict[ResultIdentity, OfflineEvaluationResult]:
        if not submissions:
            return {}
        items_by_version: dict[UUID, list[UUID]] = {}
        for result in submissions:
            items_by_version.setdefault(result.scorer_version_id, []).append(result.item_id)
        requested_pairs = Q()
        for version_id, item_ids in items_by_version.items():
            requested_pairs |= Q(scorer_version_id=version_id, item_id__in=item_ids)
        return {
            ResultIdentity(item_id=result.item_id, scorer_version_id=result.scorer_version_id): result
            for result in OfflineEvaluationResult.objects.for_team(self.team_id).filter(
                requested_pairs, item__experiment_id=experiment_id
            )
        }

    def _dataset_versions(
        self, experiment: OfflineExperiment, submissions: list[ItemSubmission]
    ) -> dict[UUID, DatasetItemVersion]:
        if not submissions:
            return {}
        linked_ids = {item.dataset_item_version_id for item in submissions if item.dataset_item_version_id is not None}
        if experiment.dataset_source != "posthog":
            if linked_ids:
                raise OfflineEvaluationValidationError(
                    "items", "PostHog item versions require a linked experiment revision."
                )
            return {}
        revision_id = experiment.dataset_revision_id
        if revision_id is None:
            raise OfflineEvaluationValidationError("items", "The experiment's dataset revision is no longer available.")
        revision = self._dataset_revisions().filter(id=revision_id).first()
        if revision is None:
            raise OfflineEvaluationValidationError("items", "The experiment's dataset revision is no longer available.")
        return {
            version.id: version
            for version in dataset_item_versions_at_revision(
                team_id=self.team_id, dataset_id=revision.dataset_id, revision=revision.revision, archived=False
            )
            .filter(id__in=linked_ids)
            .only("id", "dataset_item_id")
            .order_by()
        }

    def _new_item(
        self,
        submission: ItemSubmission,
        *,
        experiment: OfflineExperiment,
        dataset_versions: dict[UUID, DatasetItemVersion],
        fingerprint: str,
        accepted_at: datetime,
        index: int,
    ) -> OfflineExperimentItem:
        fields: dict[str, object] = {
            field.name: getattr(submission, field.name)
            for field in dataclass_fields(submission)
            if field.name != "payload"
        }
        if experiment.dataset_source == "posthog":
            version = (
                dataset_versions.get(submission.dataset_item_version_id) if submission.dataset_item_version_id else None
            )
            if version is None:
                raise OfflineEvaluationValidationError(
                    f"items.{index}.dataset_item_version_id",
                    "Select an active item version in the experiment's dataset revision.",
                )
            errors: dict[str, str] = {}
            for field, derived in {
                "dataset_item_identifier": str(version.dataset_item_id),
                "dataset_item_version_identifier": str(version.id),
            }.items():
                try:
                    fields[field] = _provenance_identifier(
                        getattr(submission, field), derived, field=f"items.{index}.{field}"
                    )
                except OfflineEvaluationValidationError as error:
                    errors.update(error.errors)
            if errors:
                raise OfflineEvaluationValidationError.from_errors(errors)
        return OfflineExperimentItem(
            **fields,
            team_id=self.team_id,
            experiment=experiment,
            submission_fingerprint=fingerprint,
            accepted_at=accepted_at,
            payload_state=PayloadState.AVAILABLE if submission.payload is not None else PayloadState.NOT_PROVIDED,
            payload_expires_at=accepted_at + timedelta(days=30) if submission.payload is not None else None,
        )

    def _new_result(
        self,
        submission: ResultSubmission,
        *,
        version: ScoreDefinitionVersion,
        fingerprint: str,
        accepted_at: datetime,
        index: int,
    ) -> OfflineEvaluationResult:
        numeric_value = submission.value if isinstance(submission.value, float) else None
        boolean_value = submission.value if isinstance(submission.value, bool) else None
        categorical_values = submission.value if isinstance(submission.value, list) else None
        if submission.status == "ok":
            errors = validate_score_value(
                version.definition.kind,
                version.config,
                numeric_value=numeric_value,
                boolean_value=boolean_value,
                categorical_values=categorical_values,
            )
            if errors:
                raise OfflineEvaluationValidationError(f"results.{index}.value", next(iter(errors.values())))
        return OfflineEvaluationResult(
            team_id=self.team_id,
            item_id=submission.item_id,
            scorer_definition=version.definition,
            scorer_version=version,
            status=submission.status,
            numeric_value=numeric_value,
            boolean_value=boolean_value,
            categorical_values=categorical_values,
            error_code=submission.error_code,
            evaluator_trace_id=submission.evaluator_trace_id,
            evaluated_at=submission.evaluated_at,
            submission_fingerprint=fingerprint,
            accepted_at=accepted_at,
            payload_state=PayloadState.AVAILABLE if submission.payload is not None else PayloadState.NOT_PROVIDED,
            payload_expires_at=accepted_at + timedelta(days=30) if submission.payload is not None else None,
        )

    def upload(self, experiment_id: UUID, submission: UploadSubmission) -> UploadReceipt:
        item_hashes = {item.id: submission_fingerprint(item) for item in submission.items}
        result_hashes = [submission_fingerprint(result) for result in submission.results]
        try:
            with transaction.atomic():
                experiment = _locked_experiment(team_id=self.team_id, experiment_id=experiment_id)
                receipt = self._upload_locked(
                    experiment, submission, item_hashes=item_hashes, result_hashes=result_hashes
                )
        except IntegrityError as error:
            _raise_integrity_conflict(error)
        return receipt

    def _upload_locked(
        self,
        experiment: OfflineExperiment,
        submission: UploadSubmission,
        *,
        item_hashes: dict[UUID, str],
        result_hashes: list[str],
    ) -> UploadReceipt:
        item_ids = list(dict.fromkeys(result.item_id for result in submission.results))
        items = {
            item.id: item
            for item in OfflineExperimentItem.objects.for_team(self.team_id).filter(
                experiment_id=experiment.id, id__in=item_ids
            )
        }
        results = self._existing_results(experiment_id=experiment.id, submissions=submission.results)
        for index, item in enumerate(submission.items):
            if item.id in items:
                _check_fingerprint(
                    items[item.id].submission_fingerprint, item_hashes[item.id], field=f"items.{index}.id"
                )
        new_results: list[tuple[int, ResultSubmission]] = []
        for index, result in enumerate(submission.results):
            existing = results.get(ResultIdentity(item_id=result.item_id, scorer_version_id=result.scorer_version_id))
            if existing is not None:
                _check_fingerprint(existing.submission_fingerprint, result_hashes[index], field=f"results.{index}")
            else:
                new_results.append((index, result))
        new_item_submissions = [item for item in submission.items if item.id not in items]
        if (new_item_submissions or new_results) and experiment.status != OfflineExperiment.Status.UPLOADING:
            raise OfflineEvaluationConflict("experiment_closed", "This experiment is closed to new items and results.")
        errors: dict[str, str] = {}
        try:
            dataset_versions = self._dataset_versions(experiment, new_item_submissions)
        except OfflineEvaluationValidationError as error:
            errors.update(error.errors)
            dataset_versions = None
        versions = {
            version.id: version
            for version in self._scorer_versions()
            .filter(id__in={result.scorer_version_id for _, result in new_results})
            .select_related("definition")
        }
        accepted_at = timezone.now()
        new_items: list[OfflineExperimentItem] = []
        if dataset_versions is not None:
            for index, item in enumerate(submission.items):
                if item.id in items:
                    continue
                try:
                    new_items.append(
                        self._new_item(
                            item,
                            experiment=experiment,
                            dataset_versions=dataset_versions,
                            fingerprint=item_hashes[item.id],
                            accepted_at=accepted_at,
                            index=index,
                        )
                    )
                except OfflineEvaluationValidationError as error:
                    errors.update(error.errors)
        declared_item_ids = {item.id for item in submission.items}
        items.update({item.id: item for item in new_items})
        new_result_rows: list[OfflineEvaluationResult] = []
        for index, result in new_results:
            if result.item_id not in items and result.item_id not in declared_item_ids:
                errors[f"results.{index}.item_id"] = "Declare the item or select an existing item in this experiment."
            version = versions.get(result.scorer_version_id)
            if version is None:
                errors[f"results.{index}.scorer_version_id"] = "Select an existing scorer version in this project."
                continue
            try:
                row = self._new_result(
                    result, version=version, fingerprint=result_hashes[index], accepted_at=accepted_at, index=index
                )
            except OfflineEvaluationValidationError as error:
                errors.update(error.errors)
                continue
            new_result_rows.append(row)
            results[ResultIdentity(item_id=result.item_id, scorer_version_id=result.scorer_version_id)] = row
        if errors:
            raise OfflineEvaluationValidationError.from_errors(errors)
        OfflineExperimentItem.objects.for_team(self.team_id).bulk_create(new_items)
        new_item_ids = {item.id for item in new_items}
        OfflineExperimentItemPayload.objects.for_team(self.team_id).bulk_create(
            [
                OfflineExperimentItemPayload(team_id=self.team_id, item_id=item.id, data=item.payload)
                for item in submission.items
                if item.id in new_item_ids and item.payload is not None
            ]
        )
        OfflineEvaluationResult.objects.for_team(self.team_id).bulk_create(new_result_rows)
        new_result_ids = {result.id for result in new_result_rows}
        OfflineEvaluationResultPayload.objects.for_team(self.team_id).bulk_create(
            [
                OfflineEvaluationResultPayload(
                    team_id=self.team_id,
                    result=results[ResultIdentity(item_id=result.item_id, scorer_version_id=result.scorer_version_id)],
                    data=result.payload,
                )
                for _, result in new_results
                if result.payload is not None
            ]
        )
        return UploadReceipt(
            items=[
                ItemReceipt(id=item.id, accepted_at=item.accepted_at, created=item.id in new_item_ids)
                for item in (items[id] for id in item_ids)
            ],
            results=[
                ResultReceipt(
                    id=row.id,
                    item_id=row.item_id,
                    scorer_version_id=row.scorer_version_id,
                    accepted_at=row.accepted_at,
                    created=row.id in new_result_ids,
                )
                for row in (
                    results[ResultIdentity(item_id=result.item_id, scorer_version_id=result.scorer_version_id)]
                    for result in submission.results
                )
            ],
        )
