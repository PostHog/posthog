import json
import typing


class PostHogWorkflow:
    """Base class for Temporal Workflows that can be executed in PostHog."""

    # Subclasses can declare these to inherit a default parse_inputs that
    # JSON-decodes inputs[0] into inputs_cls. Set inputs_optional=True if
    # the workflow may run with no CLI inputs (returns inputs_cls()).
    inputs_cls: typing.ClassVar[type | None] = None
    inputs_optional: typing.ClassVar[bool] = False

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
        """Parse inputs from the management command CLI.

        Default implementation uses `cls.inputs_cls`. Override for custom logic.
        """
        if cls.inputs_cls is None:
            return None
        if not inputs:
            if cls.inputs_optional:
                return cls.inputs_cls()
            raise ValueError(f"Workflow {cls.__name__} requires inputs")
        return cls.inputs_cls(**json.loads(inputs[0]))
