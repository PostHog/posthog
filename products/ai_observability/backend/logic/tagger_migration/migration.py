from dataclasses import replace
from enum import StrEnum
from types import SimpleNamespace
from typing import Any

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.plugins.plugin_server_api import reload_taggers_on_workers

from products.ai_observability.backend.api.evaluations import EvaluationSerializer
from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import EvaluationTarget
from products.ai_observability.backend.models.taggers import HogTaggerConfig, LLMTaggerConfig, Tagger, TaggerType

from .evaluation_payload import conditions_payload, hog_payload, llm_judge_payload
from .tag_counts_queries import RECENT_DAYS, load_recent_tag_counts


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


def _pending_taggers(team: Team) -> list[Tagger]:
    return list(
        Tagger.objects.filter(team=team, enabled=True, deleted=False, migrated_to_evaluation_id__isnull=True)
        .select_related("model_configuration", "created_by")
        .order_by("created_at", "id")
    )


def _model_configuration(tagger: Tagger, team: Team) -> dict[str, Any] | None:
    """The tagger's model, or for a tagger without one the default model of the team's active key, which is what the
    tagger runtime resolves to."""
    config = tagger.model_configuration
    if config is not None:
        return {
            "provider": config.provider,
            "model": config.model,
            "provider_key_id": str(config.provider_key_id) if config.provider_key_id else None,
        }
    evaluation_config = EvaluationConfig.objects.filter(team=team).select_related("active_provider_key").first()
    key = evaluation_config.active_provider_key if evaluation_config else None
    model = DEFAULT_MODEL_BY_PROVIDER.get(key.provider) if key else None
    if key is None or model is None:
        return None
    return {"provider": key.provider, "model": model, "provider_key_id": str(key.id)}


def _error_text(detail: Any) -> str:
    if isinstance(detail, dict):
        return " ".join(_error_text(value) for value in detail.values())
    if isinstance(detail, list):
        return " ".join(_error_text(value) for value in detail)
    return str(detail)


def _plan(tagger: Tagger, team: Team, recent_tags: int, acting_user: User | None) -> _Planned:
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
                MigrationAction.SWITCH_OFF, f"Sent no tags in the last {RECENT_DAYS} days, so nothing replaces it."
            )
        )

    model_configuration: dict[str, Any] | None = None
    if tagger.tagger_type == TaggerType.HOG:
        hog_config = HogTaggerConfig.model_validate(tagger.tagger_config)
        if not hog_config.tags:
            return _Planned(
                step=step(MigrationAction.SKIP, "Hog tagger without a tag list. It needs one to become categories.")
            )
        payload = hog_payload(hog_config)
    else:
        payload = llm_judge_payload(LLMTaggerConfig.model_validate(tagger.tagger_config))
        model_configuration = _model_configuration(tagger, team)
        if model_configuration is None:
            return _Planned(
                step=step(MigrationAction.SKIP, "No model on the tagger and no active provider key to pick one.")
            )

    serializer = EvaluationSerializer(
        data={
            "name": tagger.name,
            "description": tagger.description,
            "enabled": True,
            "target": EvaluationTarget.GENERATION.value,
            "conditions": conditions_payload(tagger.conditions or []),
            "model_configuration": model_configuration,
            **payload,
        },
        # The evaluation belongs to whoever made the tagger, not to the staff member who migrates it.
        context={"request": SimpleNamespace(user=tagger.created_by or acting_user), "get_team": lambda: team},
    )
    keys = tuple(option["key"] for option in payload["output_config"]["options"])
    if not serializer.is_valid():
        return _Planned(step=step(MigrationAction.SKIP, _error_text(serializer.errors), keys))
    output = payload["output_config"]
    kind = "Hog code" if tagger.tagger_type == TaggerType.HOG else "LLM judge"
    choice = "single choice" if output["selection_mode"] == "single" else "multiple choice"
    na = ", N/A when no tag fits" if output["allows_na"] else ""
    return _Planned(step=step(MigrationAction.MIGRATE, f"{kind}, {choice}{na}.", keys), serializer=serializer)


def _plan_team(team: Team, acting_user: User | None) -> list[_Planned]:
    taggers = _pending_taggers(team)
    counts = load_recent_tag_counts(team, [str(tagger.id) for tagger in taggers])
    return [_plan(tagger, team, counts.get(str(tagger.id), 0), acting_user) for tagger in taggers]


def plan_tagger_migration(team: Team) -> list[TaggerMigrationStep]:
    """What `migrate_taggers` would do to each switched-on tagger of the team. Writes nothing."""
    return [planned.step for planned in _plan_team(team, acting_user=None)]


def migrate_taggers(team: Team, *, acting_user: User) -> list[TaggerMigrationStep]:
    """Replaces each switched-on tagger with an enabled categorical evaluation and switches the tagger off, or only
    switches it off when it sent no tags recently. Each tagger moves in its own transaction, so one refusal does not
    undo the others, and a second run skips taggers that already moved."""
    results: list[TaggerMigrationStep] = []
    for planned in _plan_team(team, acting_user):
        step = planned.step
        if step.action == MigrationAction.SKIP:
            results.append(step)
            continue
        with transaction.atomic():
            # The row lock makes two concurrent runs create one evaluation, not two.
            still_pending = Tagger.objects.select_for_update().filter(
                pk=step.tagger_id, enabled=True, deleted=False, migrated_to_evaluation_id__isnull=True
            )
            if not still_pending.exists():
                continue
            evaluation_id: str | None = None
            if planned.serializer is not None:
                evaluation_id = str(planned.serializer.save().id)
            # A queryset update skips Tagger.save(), which would re-validate and recompile a config that is about to
            # stop running. So the reload the save signal sends goes out here.
            still_pending.update(enabled=False, migrated_to_evaluation_id=evaluation_id)
            transaction.on_commit(
                lambda tagger_id=step.tagger_id: reload_taggers_on_workers(team_id=team.pk, tagger_ids=[tagger_id])
            )
        results.append(replace(step, evaluation_id=evaluation_id))
    return results
