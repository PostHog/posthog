from abc import abstractmethod
from typing import Any, Optional

from django.db import transaction

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.approvals.actions.base import BaseAction
from posthog.approvals.exceptions import ApplyFailed, PreconditionFailed
from posthog.models import FeatureFlag


class FeatureFlagActionBase(BaseAction):
    """Base class for feature flag state change actions."""

    resource_type = "feature_flag"
    endpoint_serializer_class = FeatureFlagSerializer
    intent_fields = ["active"]

    # Subclasses define the target state
    target_active_state: bool

    @classmethod
    def validate_intent(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        data_to_validate = intent_data.get("full_request_data", intent_data.get("gated_changes", {}))
        instance = context.get("instance") if context else None

        serializer = cls.endpoint_serializer_class(
            instance=instance,
            data=data_to_validate,
            partial=True,
            context=context or {},
        )

        is_valid = serializer.is_valid()
        return is_valid, None if is_valid else serializer.errors

    @classmethod
    def prepare_context(cls, change_request, base_context: dict) -> dict:
        context = base_context.copy()

        flag_id = change_request.intent.get("flag_id") or change_request.resource_id
        if flag_id:
            try:
                instance = FeatureFlag.objects.get(id=flag_id, team_id=change_request.team_id)
                context["instance"] = instance
            except FeatureFlag.DoesNotExist:
                pass

        return context

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        if request.method not in ["PATCH", "PUT"]:
            return False

        try:
            flag = cls._get_instance(view, *args, **kwargs)
            if not flag:
                return False
        except Exception:
            return False

        desired_active = request.data.get("active")
        current_active = flag.active

        if desired_active != cls.target_active_state or current_active == cls.target_active_state:
            return False

        team = cls._get_team(view)
        if not team:
            return False

        return True

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        flag = cls._get_instance(view, *args, **kwargs)

        gated_changes = {}
        for field in cls.intent_fields:
            if field in request.data:
                gated_changes[field] = request.data[field]

        return {
            "flag_id": flag.id,
            "flag_key": flag.key,
            "current_state": {"active": flag.active},
            "gated_changes": gated_changes,
            "full_request_data": dict(request.data),
            "preconditions": {
                "version": flag.version,
                "updated_at": flag.updated_at.isoformat() if flag.updated_at else None,
            },
        }

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user, context: Optional[dict[str, Any]] = None) -> FeatureFlag:
        with transaction.atomic():
            flag = FeatureFlag.objects.select_for_update().get(id=validated_intent["flag_id"])

            if flag.version != validated_intent["preconditions"]["version"]:
                raise PreconditionFailed(
                    f"Flag version mismatch: expected {validated_intent['preconditions']['version']}, "
                    f"got {flag.version}"
                )

            # Idempotency: already in target state
            if flag.active is cls.target_active_state:
                return flag

            serializer_context = {
                "team": context.get("team") if context else flag.team,
                "team_id": context.get("team_id") if context else flag.team_id,
                "project_id": context.get("project_id") if context else flag.team.project_id,
            }

            if context and "request" in context:
                serializer_context["request"] = context["request"]

            serializer = FeatureFlagSerializer(
                instance=flag,
                data=validated_intent["full_request_data"],
                partial=True,
                context=serializer_context,
            )

            if not serializer.is_valid():
                raise ApplyFailed(f"Serializer validation failed: {serializer.errors}")

            try:
                flag = serializer.save(last_modified_by=user)
            except Exception as e:
                raise ApplyFailed(f"Serializer save failed: {str(e)}")

        return flag

    @classmethod
    @abstractmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        """Subclasses provide action-specific display data."""
        pass


class EnableFeatureFlagAction(FeatureFlagActionBase):
    """Gate enabling feature flags in production."""

    key = "feature_flag.enable"
    version = 1
    description = "Enable a feature flag"
    target_active_state = True

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "description": f"Enable feature flag '{intent_data.get('flag_key', 'unknown')}'",
            "before": intent_data.get("current_state", {}),
            "after": intent_data.get("gated_changes", {}),
        }


class DisableFeatureFlagAction(FeatureFlagActionBase):
    """Gate disabling feature flags in production."""

    key = "feature_flag.disable"
    version = 1
    description = "Disable a feature flag"
    target_active_state = False

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "description": f"Disable feature flag '{intent_data.get('flag_key', 'unknown')}'",
            "before": intent_data.get("current_state", {}),
            "after": intent_data.get("gated_changes", {}),
        }


class UpdateFeatureFlagAction(BaseAction):
    """Gate feature flag field-level updates based on policy conditions."""

    key = "feature_flag.update"
    version = 1
    description = "Update feature flag fields"
    resource_type = "feature_flag"
    endpoint_serializer_class = FeatureFlagSerializer

    GATEABLE_FIELDS: dict[str, dict[str, str]] = {
        "rollout_percentage": {
            "type": "number",
            "display_name": "rollout percentage",
        }
    }

    ROLLOUT_PERCENTAGE_PATHS = [
        ("groups", "rollout_percentage"),
        ("super_groups", "rollout_percentage"),
        ("holdout_groups", "rollout_percentage"),
        ("multivariate", "variants", "rollout_percentage"),
    ]

    intent_fields = ["rollout_percentage"]

    @classmethod
    def _extract_rollout_percentages(cls, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract all rollout_percentage values from the filter structure.

        Locations checked are defined in ROLLOUT_PERCENTAGE_PATHS.
        Each path is a tuple of (keys_to_array..., field_name).

        Returns list of dicts with 'path' and 'value' for each found value.
        """
        results: list[dict[str, Any]] = []

        for path_spec in cls.ROLLOUT_PERCENTAGE_PATHS:
            array_path, field_name = path_spec[:-1], path_spec[-1]

            current: Any = filters
            for key in array_path:
                current = current.get(key) if isinstance(current, dict) else None
                if current is None:
                    break

            if not isinstance(current, list):
                continue

            path_str = ".".join(array_path)
            for idx, item in enumerate(current):
                if isinstance(item, dict) and field_name in item:
                    results.append(
                        {
                            "path": f"{path_str}[{idx}].{field_name}",
                            "value": item[field_name],
                        }
                    )

        return results

    @classmethod
    def _has_gateable_field_changes(cls, old_filters: dict[str, Any], new_filters: dict[str, Any]) -> bool:
        """Check if any gateable field has changed between old and new filters."""
        old_values = cls._extract_rollout_percentages(old_filters)
        new_values = cls._extract_rollout_percentages(new_filters)

        old_by_path = {v["path"]: v["value"] for v in old_values}
        new_by_path = {v["path"]: v["value"] for v in new_values}

        all_paths = set(old_by_path.keys()) | set(new_by_path.keys())

        for path in all_paths:
            old_val = old_by_path.get(path)
            new_val = new_by_path.get(path)
            if old_val != new_val:
                return True

        return False

    @classmethod
    def _get_triggered_paths(cls, old_filters: dict[str, Any], new_filters: dict[str, Any]) -> list[str]:
        """Get list of field paths that have changed."""
        old_values = cls._extract_rollout_percentages(old_filters)
        new_values = cls._extract_rollout_percentages(new_filters)

        old_by_path = {v["path"]: v["value"] for v in old_values}
        new_by_path = {v["path"]: v["value"] for v in new_values}

        all_paths = set(old_by_path.keys()) | set(new_by_path.keys())
        triggered = []

        for path in all_paths:
            old_val = old_by_path.get(path)
            new_val = new_by_path.get(path)
            if old_val != new_val:
                triggered.append(path)

        return triggered

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        if request.method not in ["PATCH", "PUT"]:
            return False

        try:
            flag = cls._get_instance(view, *args, **kwargs)
            if not flag:
                return False
        except Exception:
            return False

        desired_active = request.data.get("active")
        current_active = flag.active

        if desired_active is not None and desired_active != current_active:
            if "filters" not in request.data:
                return False

        new_filters = request.data.get("filters")
        if not new_filters:
            return False

        old_filters = flag.filters or {}

        if not cls._has_gateable_field_changes(old_filters, new_filters):
            return False

        team = cls._get_team(view)
        if not team:
            return False

        return True

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        flag = cls._get_instance(view, *args, **kwargs)

        old_filters = flag.filters or {}
        new_filters = request.data.get("filters", {})

        old_rollout_percentages = cls._extract_rollout_percentages(old_filters)
        new_rollout_percentages = cls._extract_rollout_percentages(new_filters)

        triggered_paths = cls._get_triggered_paths(old_filters, new_filters)

        return {
            "flag_id": flag.id,
            "flag_key": flag.key,
            "current_state": {
                "rollout_percentage": old_rollout_percentages,
            },
            "gated_changes": {
                "rollout_percentage": new_rollout_percentages,
            },
            "triggered_paths": triggered_paths,
            "full_request_data": dict(request.data),
            "preconditions": {
                "version": flag.version,
                "updated_at": flag.updated_at.isoformat() if flag.updated_at else None,
            },
        }

    @classmethod
    def validate_intent(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        data_to_validate = intent_data.get("full_request_data", {})
        instance = context.get("instance") if context else None

        serializer = cls.endpoint_serializer_class(
            instance=instance,
            data=data_to_validate,
            partial=True,
            context=context or {},
        )

        is_valid = serializer.is_valid()
        return is_valid, None if is_valid else serializer.errors

    @classmethod
    def prepare_context(cls, change_request, base_context: dict) -> dict:
        context = base_context.copy()

        flag_id = change_request.intent.get("flag_id") or change_request.resource_id
        if flag_id:
            try:
                instance = FeatureFlag.objects.get(id=flag_id, team_id=change_request.team_id)
                context["instance"] = instance
            except FeatureFlag.DoesNotExist:
                pass

        return context

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user, context: Optional[dict[str, Any]] = None) -> FeatureFlag:
        with transaction.atomic():
            flag = FeatureFlag.objects.select_for_update().get(id=validated_intent["flag_id"])

            if flag.version != validated_intent["preconditions"]["version"]:
                raise PreconditionFailed(
                    f"Flag version mismatch: expected {validated_intent['preconditions']['version']}, "
                    f"got {flag.version}"
                )

            serializer_context = {
                "team": context.get("team") if context else flag.team,
                "team_id": context.get("team_id") if context else flag.team_id,
                "project_id": context.get("project_id") if context else flag.team.project_id,
            }

            if context and "request" in context:
                serializer_context["request"] = context["request"]

            serializer = FeatureFlagSerializer(
                instance=flag,
                data=validated_intent["full_request_data"],
                partial=True,
                context=serializer_context,
            )

            if not serializer.is_valid():
                raise ApplyFailed(f"Serializer validation failed: {serializer.errors}")

            try:
                flag = serializer.save(last_modified_by=user)
            except Exception as e:
                raise ApplyFailed(f"Serializer save failed: {str(e)}")

        return flag

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        """Generate human-readable diff showing before/after for gated fields."""
        flag_key = intent_data.get("flag_key", "unknown")
        current_state = intent_data.get("current_state", {})
        gated_changes = intent_data.get("gated_changes", {})
        triggered_paths = intent_data.get("triggered_paths", [])

        changes_description = []
        before_values = current_state.get("rollout_percentage", [])
        after_values = gated_changes.get("rollout_percentage", [])

        before_by_path = {v["path"]: v["value"] for v in before_values}
        after_by_path = {v["path"]: v["value"] for v in after_values}

        for path in triggered_paths:
            before_val = before_by_path.get(path, "N/A")
            after_val = after_by_path.get(path, "N/A")
            field_display_name = cls.GATEABLE_FIELDS["rollout_percentage"]["display_name"]
            changes_description.append(f"{field_display_name} at {path}: {before_val}% -> {after_val}%")

        description = (
            f"Update {cls.GATEABLE_FIELDS['rollout_percentage']['display_name']} for feature flag '{flag_key}'"
        )
        if changes_description:
            description = f"{description}: {'; '.join(changes_description)}"

        return {
            "description": description,
            "before": current_state,
            "after": gated_changes,
            "triggered_paths": triggered_paths,
        }
