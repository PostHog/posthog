import copy
from typing import Any

from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.ai_observability.backend.models.evaluations import Evaluation

# Lives here, not in api/evaluations.py, so it can wire at AppConfig.ready() without dragging the
# evaluations viewset (which pulls scipy / google.genai / the ai_observability Temporal worker) onto
# the django.setup() path. Evaluations are mutated outside web requests, so the audit log must
# connect in every process.

_COMPILED_KEYS = ("bytecode", "bytecode_error")


def _strip_compiled_from_conditions(conditions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not conditions:
        return []
    return [{k: v for k, v in cond.items() if k not in _COMPILED_KEYS} for cond in conditions]


def _strip_compiled_from_eval_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not config:
        return {}
    return {k: v for k, v in config.items() if k not in _COMPILED_KEYS}


@mutable_receiver(model_activity_signal, sender=Evaluation)
def handle_evaluation_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # `save()` re-derives `conditions[*].bytecode` and `evaluation_config.bytecode` on every write.
    # Strip them on shallow copies so the diff reflects user intent, not the compiler — mutating
    # `after_update` directly would also mutate the live instance DRF serialises for the response.
    before_log = copy.copy(before_update) if before_update is not None else None
    after_log = copy.copy(after_update) if after_update is not None else None
    for snapshot in (before_log, after_log):
        if snapshot is not None:
            snapshot.conditions = _strip_compiled_from_conditions(snapshot.conditions)
            snapshot.evaluation_config = _strip_compiled_from_eval_config(snapshot.evaluation_config)

    if before_update and after_update:
        before_deleted = getattr(before_update, "deleted", None)
        after_deleted = getattr(after_update, "deleted", None)
        if before_deleted is not None and after_deleted is not None and before_deleted != after_deleted:
            activity = "restored" if after_deleted is False else "deleted"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_log, current=after_log),
            name=after_update.name,
        ),
    )
