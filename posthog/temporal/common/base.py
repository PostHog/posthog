import json
import typing

import temporalio.exceptions


class PostHogWorkflow:
    """Base class for Temporal Workflows that can be executed in PostHog."""

    # Set on subclasses to enable the default JSON-decoding parse_inputs.
    inputs_cls: typing.ClassVar[type | None] = None
    inputs_optional: typing.ClassVar[bool] = False

    @staticmethod
    def _activity_error_properties(error: Exception) -> dict[str, typing.Any]:
        if not isinstance(error, temporalio.exceptions.ActivityError):
            return {}

        retry_state = error.retry_state
        properties: dict[str, typing.Any] = {
            "temporal_activity_id": error.activity_id,
            "temporal_activity_type": error.activity_type,
            "temporal_activity_identity": error.identity,
            "temporal_activity_retry_state": retry_state.name if retry_state else None,
            "temporal_activity_scheduled_event_id": error.scheduled_event_id,
            "temporal_activity_started_event_id": error.started_event_id,
        }

        if error.cause:
            properties.update(
                {
                    "cause_error_type": type(error.cause).__name__,
                    "cause_error_message": str(error.cause)[:500],
                }
            )

        return properties

    @classmethod
    def get_name(cls) -> str:
        """Get workflow's name."""
        return getattr(cls, "__temporal_workflow_definition").name

    @classmethod
    def is_named(cls, name: str) -> bool:
        """Check if this workflow's name matches name.

        All temporal workflows have the __temporal_workflow_definition attribute
        injected into them by the defn decorator. We use it to access the name and
        avoid having to define it twice. If this changes in the future, we can
        update this method instead of changing every single workflow.
        """
        return cls.get_name() == name

    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> typing.Any:
        """Default parse_inputs uses `cls.inputs_cls`; override for custom logic."""
        if cls.inputs_cls is None:
            return None
        if not inputs:
            if cls.inputs_optional:
                return cls.inputs_cls()
            raise ValueError(f"Workflow {cls.__name__} requires inputs")
        return cls.inputs_cls(**json.loads(inputs[0]))
