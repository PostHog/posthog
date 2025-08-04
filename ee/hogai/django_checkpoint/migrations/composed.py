from typing import Any, Optional
from datetime import datetime, UTC
import logging

from .base import BaseMigration
from .operations import BaseMigrationOperation
from ee.hogai.utils.types import GraphContext, GraphType, VersionMetadata

logger = logging.getLogger(__name__)


class ComposedMigration(BaseMigration):
    """
    Base class for migrations built from composed operations.

    Subclasses define a list of operations that are applied in sequence
    to transform state objects. This provides a declarative way to build
    complex migrations from simple, reusable components.

    Subclasses must define:
    - operations: List of BaseMigrationOperation instances
    """

    operations: list[BaseMigrationOperation] = []

    @classmethod
    def _extract_version_metadata(cls, state_obj: Any) -> Optional[VersionMetadata]:
        """
        Extract VersionMetadata from a state object.

        Handles both BaseState instances and dict representations.

        Args:
            state_obj: State object to extract version metadata from

        Returns:
            VersionMetadata instance or None if not found
        """
        # Handle BaseState instances
        if hasattr(state_obj, "version_metadata"):
            return state_obj.version_metadata

        # Handle dict-based state
        elif isinstance(state_obj, dict) and "version_metadata" in state_obj:
            vm_data = state_obj["version_metadata"]

            # If it's already a VersionMetadata instance
            if isinstance(vm_data, VersionMetadata):
                return vm_data

            # If it's a dict, try to create VersionMetadata
            elif isinstance(vm_data, dict):
                try:
                    return VersionMetadata(**vm_data)
                except Exception as e:
                    logger.warning(f"Could not create VersionMetadata from dict: {e}")
                    return None

        return None

    @classmethod
    def _bump_version_and_apply(cls, state_obj: Any, new_version: int, original_vm: VersionMetadata) -> Any:
        """
        Update version metadata in a state object to the new schema version.

        Args:
            state_obj: State object to update
            new_version: New schema version number
            original_vm: Original version metadata

        Returns:
            State object with updated version metadata
        """
        updated_vm = VersionMetadata(
            schema_version=new_version,
            migrated_at=datetime.now(UTC).isoformat(),
            graph_type=original_vm.graph_type,
            context=original_vm.context,
        )

        # Handle BaseState instances
        if hasattr(state_obj, "version_metadata"):
            try:
                # Get state data
                if hasattr(state_obj, "model_dump"):
                    state_dict = state_obj.model_dump()
                else:
                    state_dict = state_obj.__dict__.copy()

                # Update version metadata
                state_dict["version_metadata"] = updated_vm

                # Recreate state object
                return type(state_obj)(**state_dict)

            except Exception as e:
                logger.exception(f"Could not recreate state object with updated version: {e}")
                # Fallback to dict
                state_dict = state_obj.__dict__.copy()
                state_dict["version_metadata"] = updated_vm.model_dump()
                return state_dict

        # Handle dict-based state
        elif isinstance(state_obj, dict):
            result = state_obj.copy()
            result["version_metadata"] = updated_vm.model_dump()
            return result

        return state_obj

    @classmethod
    def needs_migration(cls, state_obj: Any) -> bool:
        """
        Check if any operations in this migration apply to the state object.

        This is implemented generically by:
        1. Extracting version_metadata from the state object
        2. Checking if current version is less than target version
        3. Checking if any operations would apply to this state object

        Args:
            state_obj: State object to check

        Returns:
            True if migration is needed, False otherwise
        """
        # Must have version_metadata (added by Migration0001)
        version_metadata = cls._extract_version_metadata(state_obj)
        if not version_metadata:
            return False

        # Must be older than target version
        if version_metadata.schema_version >= cls.get_version():
            return False

        # Check if any operations would apply
        return any(operation.applies_to(version_metadata) for operation in cls.operations)

    @classmethod
    def apply_to_state_object(cls, state_obj: Any, graph_type: GraphType, context: GraphContext) -> Any:
        """
        Apply all operations in sequence to transform the state object.

        This is implemented generically by:
        1. Extracting version_metadata from the state object
        2. Applying each operation that matches the state object
        3. Updating version_metadata to the new schema version
        4. Returning the transformed state object

        Args:
            state_obj: State object to transform
            graph_type: Graph type (used for operation targeting)
            context: Context (used for operation targeting)

        Returns:
            Transformed state object with updated version metadata
        """
        # Extract current version metadata
        version_metadata = cls._extract_version_metadata(state_obj)
        if not version_metadata:
            logger.warning("ComposedMigration: No version metadata found, skipping")
            return state_obj

        # Apply operations in sequence
        result = state_obj
        operations_applied = 0

        for operation in cls.operations:
            if operation.applies_to(version_metadata):
                # NOTE: Version metadata can be optionally updated by the operation
                # This is useful for operations that need to modify graph_type or context
                # before applying the next operations
                result, version_metadata = operation.apply(result, version_metadata)
                operations_applied += 1

        # Update version metadata to new version
        if operations_applied > 0:
            target_version = cls.get_version()
            result = cls._bump_version_and_apply(result, target_version, version_metadata)

        return result

    @classmethod
    def describe_operations(cls) -> list[str]:
        """
        Get human-readable descriptions of all operations in this migration.

        Useful for debugging and migration documentation.

        Returns:
            List of operation descriptions
        """
        return [operation.describe() for operation in cls.operations]
