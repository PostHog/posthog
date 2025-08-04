from abc import ABC, abstractmethod
from typing import Any, Optional, TypedDict
from collections.abc import Callable
import logging

from ee.hogai.utils.types import GraphContext, GraphType, VersionMetadata

logger = logging.getLogger(__name__)


class BaseMigrationOperation(ABC):
    """
    Abstract base class for all migration operations.

    Each operation implements:
    - applies_to(): Determines if operation should be applied to a state object
    - apply(): Performs the actual transformation
    - describe(): Human readable description for debugging
    """

    def __init__(
        self,
        graph_type: Optional[GraphType] = None,
        context: Optional[GraphContext] = None,
        condition: Optional[Callable[[VersionMetadata], bool]] = None,
    ):
        """
        Initialize operation with targeting criteria.

        Args:
            graph_type: Target specific graph type
            context: Target specific context
            condition: Custom condition function using version_metadata
        """
        self.graph_type = graph_type
        self.context = context
        self.condition = condition

    def applies_to(self, version_metadata: VersionMetadata) -> bool:
        """
        Check if this operation should be applied to the given state object.

        Uses targeting criteria (graph_type, context, condition)
        to determine if this operation is relevant for this state object.

        Args:
            state_obj: The state object to check
            version_metadata: Version metadata from the state object

        Returns:
            True if operation should be applied, False otherwise
        """
        if not version_metadata:
            return False

        # Check graph_type filter
        if self.graph_type and version_metadata.graph_type != self.graph_type:
            return False

        # Check context filter
        if self.context and version_metadata.context != self.context:
            return False

        # Check custom condition
        if self.condition and not self.condition(version_metadata):
            return False

        return True

    @abstractmethod
    def apply(
        self, state_obj: dict[str, Any], version_metadata: VersionMetadata
    ) -> tuple[dict[str, Any], VersionMetadata]:
        """
        Apply this operation to the state object.

        Args:
            state_obj: The state object to transform
            version_metadata: Version metadata from the state object

        Returns:
            Tuple of (state_obj, version_metadata)
        """
        pass

    @abstractmethod
    def describe(self) -> str:
        """Return human-readable description of this operation."""
        pass


class AddFieldMigration(BaseMigrationOperation):
    """
    Add a field with a default value to matching state objects.

    Example:
        AddFieldMigration(
            graph_type="assistant",
            field="conversation_metadata",
            default={"session_id": None}
        )
    """

    def __init__(self, field: str, default: Any = None, **targeting_kwargs):
        super().__init__(**targeting_kwargs)
        self.field = field
        self.default = default

    def apply(self, state_obj: Any, version_metadata: VersionMetadata) -> tuple[Any, VersionMetadata]:
        """Add the field with default value if it doesn't exist."""
        # Handle BaseState instances
        if hasattr(state_obj, "model_dump"):
            state_dict = state_obj.model_dump()
            if self.field not in state_dict:
                state_dict[self.field] = self.default
                try:
                    return type(state_obj)(**state_dict), version_metadata
                except Exception as e:
                    logger.warning(f"AddFieldMigration: Could not recreate state object: {e}")
                    return state_dict
            return state_obj

        # Handle dict-based state
        elif isinstance(state_obj, dict):
            if self.field not in state_obj:
                result = state_obj.copy()
                result[self.field] = self.default
                return result, version_metadata
            return state_obj, version_metadata

        return state_obj, version_metadata

    def describe(self) -> str:
        filters = []
        if self.graph_type:
            filters.append(f"graph_type={self.graph_type}")
        if self.context:
            filters.append(f"context={self.context}")

        filter_str = f" (where {', '.join(filters)})" if filters else ""
        return f"Add field '{self.field}' with default {self.default}{filter_str}"


class RemoveFieldMigration(BaseMigrationOperation):
    """
    Remove a field from matching state objects.

    Example:
        RemoveFieldMigration(
            graph_type="assistant",
            field="legacy_field"
        )
    """

    def __init__(self, field: str, **targeting_kwargs):
        super().__init__(**targeting_kwargs)
        self.field = field

    def apply(self, state_obj: Any, version_metadata: VersionMetadata) -> tuple[Any, VersionMetadata]:
        """Remove the field if it exists."""
        # Handle BaseState instances
        if hasattr(state_obj, "model_dump"):
            state_dict = state_obj.model_dump()
            if self.field in state_dict:
                state_dict.pop(self.field)
                try:
                    return type(state_obj)(**state_dict), version_metadata
                except Exception as e:
                    logger.warning(f"RemoveFieldMigration: Could not recreate state object: {e}")
                    return state_dict
            return state_obj, version_metadata

        # Handle dict-based state
        elif isinstance(state_obj, dict):
            if self.field in state_obj:
                result = state_obj.copy()
                result.pop(self.field)
                return result, version_metadata
            return state_obj, version_metadata

        return state_obj, version_metadata

    def describe(self) -> str:
        filters = []
        if self.graph_type:
            filters.append(f"graph_type={self.graph_type}")
        if self.context:
            filters.append(f"context={self.context}")

        filter_str = f" (where {', '.join(filters)})" if filters else ""
        return f"Remove field '{self.field}'{filter_str}"


class RenameFieldMigration(BaseMigrationOperation):
    """
    Rename a field in matching state objects.

    Example:
        RenameFieldMigration(
            graph_type="assistant",
            context="root",
            old_field="plan",
            new_field="insight_plan"
        )
    """

    def __init__(self, old_field: str, new_field: str, **targeting_kwargs):
        super().__init__(**targeting_kwargs)
        self.old_field = old_field
        self.new_field = new_field

    def apply(self, state_obj: Any, version_metadata: VersionMetadata) -> tuple[Any, VersionMetadata]:
        """Rename the field if it exists."""
        # Handle BaseState instances
        if hasattr(state_obj, "model_dump"):
            state_dict = state_obj.model_dump()
            if self.old_field in state_dict and self.new_field not in state_dict:
                state_dict[self.new_field] = state_dict.pop(self.old_field)
                try:
                    return type(state_obj)(**state_dict), version_metadata
                except Exception as e:
                    logger.warning(f"RenameFieldMigration: Could not recreate state object: {e}")
                    return state_dict
            return state_obj

        # Handle dict-based state
        elif isinstance(state_obj, dict):
            if self.old_field in state_obj and self.new_field not in state_obj:
                result = state_obj.copy()
                result[self.new_field] = result.pop(self.old_field)
                return result, version_metadata
            return state_obj, version_metadata

        return state_obj, version_metadata

    def describe(self) -> str:
        filters = []
        if self.graph_type:
            filters.append(f"graph_type={self.graph_type}")
        if self.context:
            filters.append(f"context={self.context}")

        filter_str = f" (where {', '.join(filters)})" if filters else ""
        return f"Rename field '{self.old_field}' to '{self.new_field}'{filter_str}"


class TransformFieldMigration(BaseMigrationOperation):
    """
    Transform field values using a function.

    Example:
        TransformFieldMigration(
            field="messages",
            transform=lambda messages: [msg for msg in messages if msg.get("type") != "deprecated"]
        )
    """

    def __init__(self, field: str, transform: Callable[[Any], Any], **targeting_kwargs):
        super().__init__(**targeting_kwargs)
        self.field = field
        self.transform = transform

    def apply(self, state_obj: Any, version_metadata: VersionMetadata) -> tuple[Any, VersionMetadata]:
        """Transform the field value if it exists."""
        # Handle BaseState instances
        if hasattr(state_obj, "model_dump"):
            state_dict = state_obj.model_dump()
            if self.field in state_dict:
                try:
                    state_dict[self.field] = self.transform(state_dict[self.field])
                    return type(state_obj)(**state_dict), version_metadata
                except Exception as e:
                    logger.warning(f"TransformFieldMigration: Could not transform/recreate: {e}")
                    return state_obj, version_metadata
            return state_obj, version_metadata

        # Handle dict-based state
        elif isinstance(state_obj, dict):
            if self.field in state_obj:
                result = state_obj.copy()
                try:
                    result[self.field] = self.transform(result[self.field])
                    return result, version_metadata
                except Exception as e:
                    logger.warning(f"TransformFieldMigration: Could not transform field: {e}")
                    return state_obj, version_metadata
            return state_obj, version_metadata

        return state_obj, version_metadata

    def describe(self) -> str:
        filters = []
        if self.graph_type:
            filters.append(f"graph_type={self.graph_type}")
        if self.context:
            filters.append(f"context={self.context}")

        filter_str = f" (where {', '.join(filters)})" if filters else ""
        return f"Transform field '{self.field}' using function{filter_str}"


class SplitStateMigrationDestination(TypedDict):
    fields: Optional[list[str]]  # Fields to copy from source to destination
    add_fields: Optional[dict[str, Any]]  # Fields to add to destination, mapped to values


class SplitStateMigration(BaseMigrationOperation):
    """
    Split one state type into multiple destination states based on conditions.

    This is a complex operation that:
    1. Determines which destination state this object should become
    2. Maps fields from source to destination
    3. Creates new state object of the correct type

    Example:
        SplitStateMigration(
            graph_type="assistant",
            condition=lambda vm: vm.context == "subgraph",
            destination_states={
                "insights": {
                    "fields": ["insight_plan", "rag_context"],
                    "add_fields": {"insights_type": "trend"}
                },
                "conversation": {
                    "fields": ["messages", "start_id"],
                    "add_fields": {"session_metadata": {}}
                }
            },
            routing_logic=lambda state_obj, vm: "insights" if "plan" in state_obj else "conversation"
        )
    """

    def __init__(
        self,
        graph_type: GraphType,
        destination_graph_types: dict[GraphType, SplitStateMigrationDestination],
        routing_logic: Callable[[Any, VersionMetadata], GraphType],
        **targeting_kwargs,
    ):
        super().__init__(**targeting_kwargs)
        self.graph_type = graph_type
        self.destination_graph_types = destination_graph_types
        self.routing_logic = routing_logic

    def applies_to(self, version_metadata: VersionMetadata) -> bool:
        """Override to check source state type specifically."""
        if not super().applies_to(version_metadata):
            return False

        # Must match the source graph type
        if version_metadata and version_metadata.graph_type != self.graph_type:
            return False

        return True

    def apply(self, state_obj: Any, version_metadata: VersionMetadata) -> tuple[Any, VersionMetadata]:
        """Split the state object into the appropriate destination state."""
        try:
            # Determine destination state
            destination_graph_type = self.routing_logic(state_obj, version_metadata)

            if destination_graph_type not in self.destination_graph_types:
                logger.warning(f"SplitStateMigration: Unknown destination graph type '{destination_graph_type}'")
                return state_obj, version_metadata

            dest_config = self.destination_graph_types[destination_graph_type]

            # Get source data
            if hasattr(state_obj, "model_dump"):
                source_dict = state_obj.model_dump()
            elif isinstance(state_obj, dict):
                source_dict = state_obj.copy()
            else:
                logger.warning(f"SplitStateMigration: Cannot split unsupported state object type")
                return state_obj, version_metadata

            # Build destination state dict
            dest_dict = {}

            # Copy specified fields
            fields = dest_config.get("fields", [])
            if fields:
                for field in fields:
                    if field in source_dict:
                        dest_dict[field] = source_dict[field]

            # Add new fields
            add_fields = dest_config.get("add_fields", {})
            if add_fields:
                dest_dict.update(add_fields)

            version_metadata = version_metadata.model_copy()
            version_metadata.graph_type = destination_graph_type

            dest_dict["version_metadata"] = version_metadata.model_dump()

            if hasattr(state_obj, "model_dump"):
                return type(state_obj)(**dest_dict), version_metadata
            elif isinstance(state_obj, dict):
                return dest_dict, version_metadata
            return state_obj, version_metadata

        except Exception as e:
            logger.exception(f"SplitStateMigration: Failed to split state: {e}")
            return state_obj, version_metadata

    def describe(self) -> str:
        dest_names = list(self.destination_graph_types.keys())
        return f"Split {self.graph_type} into {dest_names}"


class UpdateVersionMetadataMigration(BaseMigrationOperation):
    """
    Update version_metadata fields (graph_type, context).

    This operation allows renaming or updating the version metadata fields
    themselves, which might be needed if graph types or contexts change.

    Example:
        UpdateVersionMetadataMigration(
            graph_type_map={"assistant": "conversation_assistant"},
            context_map={"main_assistant": "primary_chat"}
        )
    """

    def __init__(
        self,
        graph_type_map: Optional[dict[GraphType, GraphType]] = None,
        context_map: Optional[dict[GraphContext, GraphContext]] = None,
        **targeting_kwargs,
    ):
        super().__init__(**targeting_kwargs)
        self.graph_type_map = graph_type_map or {}
        self.context_map = context_map or {}

    def apply(self, state_obj: Any, version_metadata: VersionMetadata) -> Any:
        """Update version_metadata fields if mappings apply."""
        # Get current version metadata
        current_vm = None
        state_dict = None
        if hasattr(state_obj, "model_dump"):
            state_dict = state_obj.model_dump()
        elif isinstance(state_obj, dict):
            state_dict = state_obj.copy()
        else:
            return state_obj, version_metadata

        if state_dict and state_dict.get("version_metadata"):
            current_vm = VersionMetadata(**state_dict["version_metadata"])
        elif isinstance(state_obj, dict) and "version_metadata" in state_obj:
            vm_data = state_obj["version_metadata"]
            if isinstance(vm_data, VersionMetadata):
                current_vm = vm_data
            elif isinstance(vm_data, dict):
                try:
                    current_vm = VersionMetadata(**vm_data)
                except Exception:
                    return state_obj

        if not current_vm:
            return state_obj

        # Apply mappings
        new_graph_type = self.graph_type_map.get(current_vm.graph_type, current_vm.graph_type)
        new_context = self.context_map.get(current_vm.context, current_vm.context)

        # Check if any changes needed
        if new_graph_type == current_vm.graph_type and new_context == current_vm.context:
            return state_obj

        # Create updated version metadata
        updated_vm = VersionMetadata(
            schema_version=current_vm.schema_version,
            migrated_at=current_vm.migrated_at,
            graph_type=new_graph_type,
            context=new_context,
        )

        state_dict["version_metadata"] = updated_vm.model_dump()

        if hasattr(state_obj, "model_dump"):
            return type(state_obj)(**state_dict), version_metadata
        elif isinstance(state_obj, dict):
            return state_dict, version_metadata
        return state_obj, version_metadata

    def describe(self) -> str:
        mappings = []
        if self.graph_type_map:
            mappings.append(f"graph_type: {self.graph_type_map}")
        if self.context_map:
            mappings.append(f"context: {self.context_map}")

        return f"Update version metadata: {', '.join(mappings)}"
