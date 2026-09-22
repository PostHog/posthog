from typing import Any, Optional

from products.approvals.backend.actions.base import BaseAction
from products.approvals.backend.exceptions import ApplyFailed, PreconditionFailed


def _exclusion_percentage(filters: Any) -> Optional[float]:
    """Read the exclusion percentage a holdout's filters carry, or None when they carry none."""
    if not isinstance(filters, list) or not filters:
        return None
    first = filters[0]
    return first.get("rollout_percentage") if isinstance(first, dict) else None


# The fields a holdout edit can write. An approved edit replays all of them, so a change
# that also renames the holdout does not lose the rename on apply.
HOLDOUT_WRITABLE_FIELDS = ("name", "description", "filters")


def _affected_experiments(holdout) -> list[dict[str, Any]]:
    """The experiments whose flag this holdout rewrites, as stable display data."""
    return [
        {"id": experiment.id, "name": experiment.name, "flag_key": experiment.feature_flag.key}
        for experiment in holdout.experiment_set.select_related("feature_flag")
        if experiment.feature_flag is not None
    ]


class ExperimentHoldoutActionBase(BaseAction):
    """Gate a holdout change as one operation, rather than each flag write it fans out into.

    A holdout edit rewrites the holdout block on every linked experiment's flag. Gating each of
    those writes would raise ApprovalRequired inside the transaction that keeps the flags and the
    holdout row consistent, and the rollback would take the pending change request with it. Gating
    the operation means the only work before the gate is a read, so nothing rolls back and one
    approval covers every flag the change touches.
    """

    resource_type = "experiment_holdout"
    # TODO(experiment-approval-policies): until experiment-owned flags leave `feature_flag.*`
    # scope, an organization's flag policy still gates the flag writes a holdout change makes.
    fallback_policy_action_keys = ("feature_flag.update",)

    @classmethod
    def _holdout(cls, view, *args, **kwargs):
        instance = cls._get_instance(view, *args, **kwargs)
        return instance if instance is not None and hasattr(instance, "experiment_set") else None

    @classmethod
    def _load_holdout(cls, holdout_id, team_id):
        # Imported from the holdout API module: approvals may depend on `ee`, not on the
        # experiments product. See tach.toml.
        from ee.clickhouse.views.experiment_holdouts import ExperimentHoldout

        # nosemgrep: idor-lookup-without-team (team_id comes from the approved change request)
        return ExperimentHoldout.objects.filter(id=holdout_id, team_id=team_id).first()

    @classmethod
    def _experiment_ids(cls, intent_data: dict[str, Any]) -> list[int]:
        return sorted(experiment["id"] for experiment in intent_data.get("affected_experiments", []))

    @classmethod
    def check_staleness(cls, intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None) -> bool:
        holdout = context.get("instance") if context else None
        if holdout is None:
            return True
        stored = intent_data.get("current_state", {}).get("exclusion_percentage")
        if _exclusion_percentage(holdout.filters) != stored:
            return True
        # An experiment that joined or left the holdout changes which flags the approved change
        # rewrites, so the approver saw a different blast radius than the one that would apply.
        return sorted(e["id"] for e in _affected_experiments(holdout)) != cls._experiment_ids(intent_data)

    @classmethod
    def prepare_context(cls, change_request, base_context: dict[str, Any]) -> dict[str, Any]:
        context = dict(base_context)
        holdout_id = change_request.intent.get("holdout_id") or change_request.resource_id
        context["instance"] = cls._load_holdout(holdout_id, change_request.team_id)
        return context

    @classmethod
    def validate_intent(
        cls, intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        # The endpoint serializer validates a holdout's own fields; the stored intent holds the
        # operation, not a serializer payload, so there is nothing to re-validate here.
        return True, None


class UpdateExperimentHoldoutAction(ExperimentHoldoutActionBase):
    """Gate a change to a holdout's exclusion percentage."""

    key = "experiment_holdout.update"
    version = 1
    description = "Change the exclusion percentage of an experiment holdout"

    intent_fields = ["exclusion_percentage"]

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        holdout = cls._holdout(view, *args, **kwargs)
        if holdout is None:
            return False
        change = args[1] if len(args) >= 2 and isinstance(args[1], dict) else getattr(request, "data", {}) or {}
        desired = _exclusion_percentage(change.get("filters"))
        return desired is not None and desired != _exclusion_percentage(holdout.filters)

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        holdout = cls._holdout(view, *args, **kwargs)
        change = args[1] if len(args) >= 2 and isinstance(args[1], dict) else getattr(request, "data", {}) or {}
        return {
            "holdout_id": holdout.id,
            "holdout_name": holdout.name,
            "current_state": {"exclusion_percentage": _exclusion_percentage(holdout.filters)},
            "gated_changes": {"exclusion_percentage": _exclusion_percentage(change.get("filters"))},
            "desired_filters": change.get("filters"),
            "desired_changes": {field: change[field] for field in HOLDOUT_WRITABLE_FIELDS if field in change},
            "affected_experiments": _affected_experiments(holdout),
        }

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user, context: Optional[dict[str, Any]] = None) -> Any:
        from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutSerializer

        holdout = context.get("instance") if context else None
        if holdout is None:
            raise PreconditionFailed("The holdout no longer exists")

        desired = _exclusion_percentage(validated_intent.get("desired_filters"))
        if desired is None:
            raise ApplyFailed("The change request carries no exclusion percentage")
        desired_changes = validated_intent.get("desired_changes") or {"filters": validated_intent["desired_filters"]}
        current = _exclusion_percentage(holdout.filters)
        other_fields_applied = all(
            getattr(holdout, field) == value for field, value in desired_changes.items() if field != "filters"
        )
        if current == desired and other_fields_applied:
            # Idempotency: the holdout already carries the approved change.
            return holdout
        if current != validated_intent.get("current_state", {}).get("exclusion_percentage"):
            raise PreconditionFailed("The holdout changed after this request was created")
        if sorted(e["id"] for e in _affected_experiments(holdout)) != cls._experiment_ids(validated_intent):
            raise PreconditionFailed("The experiments in this holdout changed after this request was created")

        serializer = ExperimentHoldoutSerializer(context=cls._serializer_context(holdout, context))
        try:
            # update() rewrites every linked flag and the holdout row in one transaction.
            return serializer.update(holdout, desired_changes)
        except Exception as e:
            raise ApplyFailed(f"Holdout update failed: {str(e)}")

    @classmethod
    def _serializer_context(cls, holdout, context: Optional[dict[str, Any]]) -> dict[str, Any]:
        team = (context or {}).get("team") or holdout.team
        serializer_context: dict[str, Any] = {
            "team_id": team.id,
            "project_id": team.project_id,
            "get_team": lambda: team,
            "get_organization": lambda: team.organization,
            # Already approved — keep the gate from re-firing on the holdout write.
            "approval_apply": True,
        }
        if context and "request" in context:
            serializer_context["request"] = context["request"]
        return serializer_context

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        affected = intent_data.get("affected_experiments", [])
        before = intent_data.get("current_state", {}).get("exclusion_percentage")
        after = intent_data.get("gated_changes", {}).get("exclusion_percentage")
        return {
            "description": (
                f"Change holdout '{intent_data.get('holdout_name', 'unknown')}' exclusion "
                f"from {before}% to {after}%, affecting {len(affected)} experiments"
            ),
            "before": intent_data.get("current_state", {}),
            "after": intent_data.get("gated_changes", {}),
        }


class DeleteExperimentHoldoutAction(ExperimentHoldoutActionBase):
    """Gate deleting a holdout, which stops excluding its users from every linked experiment."""

    key = "experiment_holdout.delete"
    version = 1
    description = "Delete an experiment holdout"

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        return cls._holdout(view, *args, **kwargs) is not None

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        holdout = cls._holdout(view, *args, **kwargs)
        return {
            "holdout_id": holdout.id,
            "holdout_name": holdout.name,
            "current_state": {"exclusion_percentage": _exclusion_percentage(holdout.filters)},
            "gated_changes": {"deleted": True},
            "affected_experiments": _affected_experiments(holdout),
        }

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user, context: Optional[dict[str, Any]] = None) -> Any:
        from ee.clickhouse.views.experiment_holdouts import delete_holdout_and_clear_flags

        holdout = context.get("instance") if context else None
        if holdout is None:
            # Idempotency: an already-applied delete leaves nothing to delete.
            return None

        try:
            delete_holdout_and_clear_flags(holdout, user=user, request=(context or {}).get("request"))
        except Exception as e:
            raise ApplyFailed(f"Holdout delete failed: {str(e)}")
        return None

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        affected = intent_data.get("affected_experiments", [])
        return {
            "description": (
                f"Delete holdout '{intent_data.get('holdout_name', 'unknown')}', "
                f"releasing its users into {len(affected)} experiments"
            ),
            "before": intent_data.get("current_state", {}),
            "after": intent_data.get("gated_changes", {}),
        }
