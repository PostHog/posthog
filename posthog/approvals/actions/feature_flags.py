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
