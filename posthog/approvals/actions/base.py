from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseAction(ABC):
    """
    Base class for all gatable actions.

    Each action defines:
    - How to detect if a request matches
    - How to extract intent from a request
    - How to validate intent
    - How to apply the change when approved
    """

    key: Optional[str] = None
    version: int = 1
    description: Optional[str] = None
    resource_type: Optional[str] = None

    endpoint_serializer_class: Optional[Any] = None

    intent_fields: Optional[list[str]] = None

    @classmethod
    def _get_instance(cls, view, *args, **kwargs):
        if hasattr(view, "context") and "request" in view.context:
            # Serializer context
            return args[0] if args else None
        else:
            # ViewSet context
            return view.get_object()

    @classmethod
    def _get_team(cls, view):
        if hasattr(view, "context"):
            return view.context.get("get_team", lambda: None)()
        else:
            return getattr(view, "team", None)

    @classmethod
    def _get_organization(cls, view):
        if hasattr(view, "context"):
            return view.context.get("get_organization", lambda: None)()
        else:
            return getattr(view, "organization", None)

    @classmethod
    def prepare_context(cls, change_request, base_context: dict[str, Any]) -> dict[str, Any]:
        """
        Prepare context for validation and apply operations.
        Override this to add resource-specific context (e.g., fetch instance).
        """
        return base_context

    @classmethod
    @abstractmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        """
        Return True if this request should be gated by this action.
        Called by the decorator to determine if this action applies.
        """
        pass

    @classmethod
    @abstractmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        """
        Extract structured intent data from the request.
        For UPDATE actions: Return current state + desired state + preconditions
        For CREATE actions: Return full payload
        """
        pass

    @classmethod
    def validate_intent(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        """
        Validate intent against the endpoint serializer.
        """
        if cls.endpoint_serializer_class is None:
            return True, None

        if "gated_changes" in intent_data:
            data_to_validate = intent_data["gated_changes"]
            partial = True
        else:
            data_to_validate = intent_data
            partial = False

        instance = context.get("instance") if context else None

        serializer = cls.endpoint_serializer_class(
            instance=instance,
            data=data_to_validate,
            partial=partial,
            context=context or {},
        )

        is_valid = serializer.is_valid()
        return is_valid, None if is_valid else serializer.errors

    @classmethod
    @abstractmethod
    def apply(
        cls,
        validated_intent: dict[str, Any],
        user,
        context: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        Execute the approved change.

        Must be idempotent and check preconditions.
        Should raise PreconditionFailed if resource changed.
        """
        pass

    @classmethod
    def get_display_data(cls, intent: dict[str, Any]) -> dict[str, Any]:
        """
        Generate human-readable diff for UI display.
        """
        if "gated_changes" in intent and "current_state" in intent:
            return {
                "before": intent["current_state"],
                "after": intent["gated_changes"],
                "changes": cls._compute_diff(
                    intent["current_state"],
                    intent["gated_changes"],
                ),
            }
        else:
            return intent

    @staticmethod
    def _compute_diff(before: dict, after: dict) -> list:
        """Compute field-level diff between states"""
        changes = []
        all_keys = set(before.keys()) | set(after.keys())

        for key in all_keys:
            before_val = before.get(key)
            after_val = after.get(key)

            if before_val != after_val:
                changes.append(
                    {
                        "field": key,
                        "before": before_val,
                        "after": after_val,
                    }
                )

        return changes
