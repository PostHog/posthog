from dataclasses import replace
from enum import StrEnum
from functools import partial
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.plugins.plugin_server_api import reload_taggers_on_workers

from products.access_control.backend.facade.api import access_rules, object_ids_with_rules
from products.ai_observability.backend.api.evaluations import EvaluationSerializer
from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import (
    EvaluationStatus,
    EvaluationStatusReason,
    EvaluationTarget,
)
from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.ai_observability.backend.models.taggers import HogTaggerConfig, LLMTaggerConfig, Tagger, TaggerType

from .evaluation_payload import conditions_payload, hog_payload, llm_judge_payload
from .tag_counts_queries import MAX_SENT_TAG_NAMES, RECENT_DAYS, load_recent_tag_counts, load_sent_tag_names


class MigrationAction(StrEnum):
    MIGRATE = "migrate"
    SWITCH_OFF = "switch_off"
    SKIP = "skip"


@frozen
class TaggerMigrationStep:
    tagger_id: str
    tagger_name: str
    tagger_type: str
    recent_tags: int
    action: MigrationAction
    reason: str
    category_keys: tuple[str, ...] = ()
    evaluation_id: str | None = None


@frozen
class TaggerCounts:
    switched_on: int
    migrated: int


def count_taggers(team: Team) -> TaggerCounts:
    taggers = Tagger.objects.filter(team=team, deleted=False)
    return TaggerCounts(
        switched_on=taggers.filter(enabled=True).count(),
        migrated=taggers.filter(migrated_to_evaluation_id__isnull=False).count(),
    )


@frozen
class _Planned:
    step: TaggerMigrationStep
    serializer: EvaluationSerializer | None = None
    # Set when the evaluation starts switched off for a key problem, so the settings page offers to turn it back on.
    key_problem: EvaluationStatusReason | None = None


def _pending_taggers(team: Team) -> list[Tagger]:
    return list(
        Tagger.objects.filter(team=team, enabled=True, deleted=False, migrated_to_evaluation_id__isnull=True)
        .select_related("model_configuration", "created_by")
        .order_by("created_at", "id")
    )


def _model_configuration(tagger: Tagger, team: Team) -> dict[str, Any] | None:
    """The tagger's model, or for a tagger without one the provider and default model of the team's active key. The
    evaluation pins that provider and model but not the key, so it uses whichever key of that provider is active.
    Without an active key it gets the OpenAI default the tagger runtime falls back to, since a judge needs a model."""
    config = tagger.model_configuration
    if config is not None:
        return {
            "provider": config.provider,
            "model": config.model,
            "provider_key_id": str(config.provider_key_id) if config.provider_key_id else None,
        }
    evaluation_config = EvaluationConfig.objects.filter(team=team).select_related("active_provider_key").first()
    key = evaluation_config.active_provider_key if evaluation_config else None
    provider = key.provider if key else "openai"
    model = DEFAULT_MODEL_BY_PROVIDER.get(provider)
    if model is None:
        return None
    return {"provider": provider, "model": model, "provider_key_id": None}


def _key_problem(team: Team, model_configuration: dict[str, Any] | None) -> EvaluationStatusReason:
    """Why an evaluation can't run on the key it would use: its pinned key, or else the team's active key when that
    key is for the evaluation's provider, as the runtime resolves it."""
    key_id = (model_configuration or {}).get("provider_key_id")
    if key_id:
        key = LLMProviderKey.objects.filter(team=team, id=key_id).first()
    else:
        config = EvaluationConfig.objects.filter(team=team).select_related("active_provider_key").first()
        key = config.active_provider_key if config else None
        if key is not None and model_configuration is not None and key.provider != model_configuration["provider"]:
            key = None
    if key is None:
        return EvaluationStatusReason.PROVIDER_KEY_REQUIRED
    if key.state != LLMProviderKey.State.OK:
        return EvaluationStatusReason.PROVIDER_KEY_INVALID
    return EvaluationStatusReason.NO_DEFAULT_MODEL


def _error_text(detail: Any) -> str:
    if isinstance(detail, dict):
        return " ".join(_error_text(value) for value in detail.values())
    if isinstance(detail, list):
        return " ".join(_error_text(value) for value in detail)
    return str(detail)


@frozen
class _AccessRules:
    """Tagger access rules an evaluation would not carry. Migrating past them would widen who can see or edit the
    copied prompt or code, because taggers and evaluations are separate access-control resources."""

    tagger_ids_with_own_rules: frozenset[str]
    resource_rules_differ: bool


@frozen
class _Grant:
    access_level: str
    organization_member_id: UUID | None
    role_id: UUID | None


def _access_rules(team: Team) -> _AccessRules:
    def resource_wide(resource: str) -> set[_Grant]:
        return {
            _Grant(
                access_level=rule.access_level, organization_member_id=rule.organization_member_id, role_id=rule.role_id
            )
            for rule in access_rules(team_id=team.pk, resources=[resource])
            if rule.resource_id is None and rule.applies
        }

    return _AccessRules(
        tagger_ids_with_own_rules=frozenset(object_ids_with_rules(team_id=team.pk, resource="tagger")),
        resource_rules_differ=resource_wide("tagger") != resource_wide("evaluation"),
    )


def _sent_tags(team: Team, taggers: list[Tagger], counts: dict[str, int]) -> dict[str, tuple[str, ...]]:
    """The tags sent by each Hog tagger that has no tag list, the only taggers whose categories come from them."""
    return load_sent_tag_names(
        team,
        [
            str(tagger.id)
            for tagger in taggers
            if tagger.tagger_type == TaggerType.HOG
            and not (tagger.tagger_config or {}).get("tags")
            and counts.get(str(tagger.id))
        ],
    )


def _plan(
    tagger: Tagger,
    team: Team,
    recent_tags: int,
    rules: _AccessRules,
    move_capped: bool,
    sent_tags: tuple[str, ...] = (),
) -> _Planned:
    def step(action: MigrationAction, reason: str, keys: tuple[str, ...] = ()) -> TaggerMigrationStep:
        return TaggerMigrationStep(
            tagger_id=str(tagger.id),
            tagger_name=tagger.name,
            tagger_type=tagger.tagger_type,
            recent_tags=recent_tags,
            action=action,
            reason=reason,
            category_keys=keys,
        )

    if recent_tags == 0:
        return _Planned(
            step=step(
                MigrationAction.SWITCH_OFF, f"It did not run in the last {RECENT_DAYS} days, so nothing replaces it."
            )
        )
    if str(tagger.id) in rules.tagger_ids_with_own_rules:
        return _Planned(step=step(MigrationAction.SKIP, "It has its own access rules, which an evaluation won't get."))
    if rules.resource_rules_differ:
        return _Planned(
            step=step(
                MigrationAction.SKIP, "Tagger access rules differ from evaluation access rules. Match them first."
            )
        )

    model_configuration: dict[str, Any] | None = None
    capped = False
    from_sent_tags = False
    try:
        if tagger.tagger_type == TaggerType.HOG:
            hog_config = HogTaggerConfig.model_validate(tagger.tagger_config)
            from_sent_tags = not hog_config.tags
            if from_sent_tags and not sent_tags:
                return _Planned(
                    step=step(
                        MigrationAction.SKIP,
                        f"It has no tag list, and sent no tags in the last {RECENT_DAYS} days to use as categories.",
                    )
                )
            if from_sent_tags and len(sent_tags) >= MAX_SENT_TAG_NAMES:
                return _Planned(
                    step=step(
                        MigrationAction.SKIP,
                        "It has no tag list, and sent more different tags than an evaluation has categories.",
                    )
                )
            payload = hog_payload(hog_config, sent_tags)
        else:
            llm_config = LLMTaggerConfig.model_validate(tagger.tagger_config)
            capped = llm_config.max_tags is not None and 1 < llm_config.max_tags < len(llm_config.tags)
            if capped and not move_capped:
                return _Planned(
                    step=step(
                        MigrationAction.SKIP,
                        f"It allows at most {llm_config.max_tags} tags, and an evaluation can only ask for that in "
                        "its prompt.",
                    )
                )
            payload = llm_judge_payload(llm_config)
            model_configuration = _model_configuration(tagger, team)
            if model_configuration is None:
                return _Planned(
                    step=step(
                        MigrationAction.SKIP, "The team's provider key has no default model, so pick a model first."
                    )
                )
    except PydanticValidationError as error:
        return _Planned(step=step(MigrationAction.SKIP, f"Its saved config is no longer valid: {error}"))

    def evaluation_serializer(enabled: bool) -> EvaluationSerializer:
        return EvaluationSerializer(
            data={
                "name": tagger.name,
                "description": tagger.description,
                "enabled": enabled,
                "target": EvaluationTarget.GENERATION.value,
                "conditions": conditions_payload(tagger.conditions or []),
                "model_configuration": model_configuration,
                **payload,
            },
            # The evaluation belongs to whoever made the tagger, never to the staff member who migrates it.
            context={"request": SimpleNamespace(user=tagger.created_by), "get_team": lambda: team},
        )

    keys = tuple(option["key"] for option in payload["output_config"]["options"])
    serializer = evaluation_serializer(enabled=True)
    switched_off = ""
    key_problem = None
    if not serializer.is_valid() and set(serializer.errors) == {"enabled"}:
        # Only the enabled check failed, so the team has no working key. The tagger can't run without one either,
        # so the evaluation keeps its config switched off until the team fixes the key.
        switched_off = f" It starts switched off: {_error_text(serializer.errors)}"
        key_problem = _key_problem(team, model_configuration)
        serializer = evaluation_serializer(enabled=False)
    if not serializer.is_valid():
        return _Planned(step=step(MigrationAction.SKIP, _error_text(serializer.errors), keys))
    output = payload["output_config"]
    kind = "Hog code" if tagger.tagger_type == TaggerType.HOG else "LLM judge"
    choice = "single choice" if output["selection_mode"] == "single" else "multiple choice"
    na = ", N/A when no tag fits" if output["allows_na"] else ""
    cap = f", the prompt asks for at most {llm_config.max_tags} tags" if capped else ""
    sent = (
        f", the categories are the tags it sent in the last {RECENT_DAYS} days, and a tag it never sent is dropped"
        if from_sent_tags
        else ""
    )
    return _Planned(
        step=step(MigrationAction.MIGRATE, f"{kind}, {choice}{na}{cap}{sent}.{switched_off}", keys),
        serializer=serializer,
        key_problem=key_problem,
    )


def plan_tagger_migration(team: Team, *, move_capped: bool = False) -> list[TaggerMigrationStep]:
    """What `migrate_taggers` would do to each switched-on tagger of the team. Writes nothing."""
    taggers = _pending_taggers(team)
    counts = load_recent_tag_counts(team, [str(tagger.id) for tagger in taggers])
    rules = _access_rules(team)
    sent = _sent_tags(team, taggers, counts)
    return [
        _plan(tagger, team, counts.get(str(tagger.id), 0), rules, move_capped, sent.get(str(tagger.id), ())).step
        for tagger in taggers
    ]


def migrate_taggers(team: Team, *, move_capped: bool = False) -> list[TaggerMigrationStep]:
    """Replaces each switched-on tagger with an enabled categorical evaluation and switches the tagger off, or only
    switches it off when it sent no tags recently. Each tagger moves in its own transaction, so one refusal does not
    undo the others, and a second run skips taggers that already moved. An LLM tagger that caps its tags below its
    tag count moves only with `move_capped`, because the evaluation can ask for the cap but not enforce it. A Hog
    tagger without a tag list moves with the tags it sent recently as its categories. When the team has no working
    provider key, the evaluation is created switched off."""
    taggers = _pending_taggers(team)
    counts = load_recent_tag_counts(team, [str(tagger.id) for tagger in taggers])
    sent = _sent_tags(team, taggers, counts)
    results: list[TaggerMigrationStep] = []
    for pending in taggers:
        recent_tags = counts.get(str(pending.id), 0)
        try:
            with transaction.atomic():
                # The row lock makes two concurrent runs create one evaluation, not two. Planning again from the
                # locked row keeps an edit made since the preview.
                still_pending = Tagger.objects.select_for_update(of=("self",)).filter(
                    team=team, pk=pending.pk, enabled=True, deleted=False, migrated_to_evaluation_id__isnull=True
                )
                tagger = still_pending.select_related("model_configuration", "created_by").first()
                if tagger is None:
                    continue
                # Access rules are read under the lock too, so a restriction added during the run still holds.
                planned = _plan(
                    tagger, team, recent_tags, _access_rules(team), move_capped, sent.get(str(tagger.id), ())
                )
                step = planned.step
                if step.action == MigrationAction.SKIP:
                    results.append(step)
                    continue
                evaluation_id = None
                if planned.serializer is not None:
                    evaluation = planned.serializer.save()
                    if planned.key_problem is not None:
                        evaluation.set_status(EvaluationStatus.ERROR, planned.key_problem)
                    evaluation_id = str(evaluation.id)
                # A queryset update skips Tagger.save(), which would re-validate and recompile a config that is
                # about to stop running. So the reload the save signal sends goes out here. Workers also reload
                # every few minutes, so a failed message must not undo or stop the migration.
                still_pending.update(enabled=False, migrated_to_evaluation_id=evaluation_id)
                transaction.on_commit(
                    partial(reload_taggers_on_workers, team_id=team.pk, tagger_ids=[str(tagger.id)]), robust=True
                )
        except (DjangoValidationError, DRFValidationError) as error:
            detail = error.detail if isinstance(error, DRFValidationError) else error.messages
            results.append(
                TaggerMigrationStep(
                    tagger_id=str(pending.id),
                    tagger_name=pending.name,
                    tagger_type=pending.tagger_type,
                    recent_tags=recent_tags,
                    action=MigrationAction.SKIP,
                    reason=f"Saving the evaluation failed: {_error_text(detail)}",
                )
            )
            continue
        results.append(replace(step, evaluation_id=evaluation_id))
    return results
