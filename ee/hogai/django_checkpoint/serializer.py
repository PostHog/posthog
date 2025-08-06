import logging
import json
from typing import Any, Optional
from langgraph.checkpoint.serde.base import SerializerProtocol
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from .migrations.migration_registry import migration_registry
from .class_registry import class_registry

logger = logging.getLogger(__name__)


class CheckpointSerializer(SerializerProtocol):
    """
    Checkpoint serializer that applies migrations during serialization.

    Instead of relying on JSONPlusSerializer, which stores entire Pydantic models on database,
    we use our own serializer, that transforms data to a versioned JSON.
    This allows us to store simple objects, that we can then reconstruct using Pydantic models when deserializing.

    Data is versioned, and migrations are applied during deserialization.
    """

    DATA_TYPE = "json"

    def __init__(self):
        # For reading legacy msgpack data
        self.legacy = JsonPlusSerializer()

        self.migration_registry = migration_registry
        self.class_registry = class_registry

    def dumps(self, obj: Any) -> bytes:
        return self.dumps_typed(obj)[1]

    def loads(self, data: bytes) -> Any:
        return self.loads_typed((self.DATA_TYPE, data))

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        """
        Serialize object with version tracking.

        Store data in a simple, version-tracked format without module paths.
        """
        if obj is None:
            return (self.DATA_TYPE, json.dumps(None).encode("utf-8"))

        # Extract data from Pydantic models
        if hasattr(obj, "model_dump"):
            data = self._prepare_for_serialization(obj)
            type_hint = obj.__class__.__name__
        else:
            # Not a Pydantic model
            data = obj
            type_hint = type(obj).__name__

        # Create versioned checkpoint
        checkpoint = {
            "_type": type_hint,
            "_version": self.migration_registry.current_version,
            "_data": data,
        }

        return (self.DATA_TYPE, json.dumps(checkpoint, default=str).encode("utf-8"))

    def _prepare_for_serialization(self, obj: Any) -> Any:
        """
        Prepare Pydantic objects for serialization.

        Adds _type field to all nested Pydantic objects so they can be
        reconstructed deterministically.
        """
        if hasattr(obj, "model_dump"):
            result = {"_type": obj.__class__.__name__}

            # Get the object's fields directly
            for field_name, _ in obj.model_fields.items():
                value = getattr(obj, field_name, None)
                if value is not None:
                    result[field_name] = self._prepare_nested_value(value)

            return result
        else:
            return obj

    def _prepare_nested_value(self, value: Any) -> Any:
        """
        Recursively prepare nested values for serialization.
        """
        if isinstance(value, list):
            return [self._prepare_for_serialization(item) if hasattr(item, "model_dump") else item for item in value]
        elif hasattr(value, "model_dump"):
            return self._prepare_for_serialization(value)
        else:
            return value

    def loads_typed(self, data: tuple[Optional[str], bytes]) -> Any:
        """
        Deserialize with automatic migration.

        This is where the magic happens - old data is automatically
        migrated to the current version.
        """
        type_str, blob = data

        # Handle legacy msgpack format
        if type_str in ["msgpack", None, "null", "", "empty"]:
            # Use legacy deserializer
            if not type_str or type_str in ["null", "empty"]:
                type_str = "msgpack"

            try:
                legacy_obj = self.legacy.loads_typed((type_str, blob))

                # If it's a state object, migrate it
                if hasattr(legacy_obj, "__class__") and hasattr(legacy_obj, "model_dump"):
                    # Convert to dict for migration
                    obj_data = legacy_obj.model_dump()
                    type_hint = legacy_obj.__class__.__name__

                    migrated_data, new_type = self._apply_migrations(obj_data, type_hint, from_version=0)

                    # Reconstruct with migrated data and potentially new type
                    return self.class_registry.construct(new_type, migrated_data)

                # Not a state object, return as-is
                return legacy_obj

            except Exception as e:
                logger.warning(f"Failed to deserialize legacy {type_str}: {e}")
                return {}

        # Handle our versioned format
        if type_str == self.DATA_TYPE:
            checkpoint = json.loads(blob.decode("utf-8"))

            if checkpoint is None:
                return None

            # Extract components
            type_hint = checkpoint.get("_type", "unknown")
            version = checkpoint.get("_version", 0)
            data_dict = checkpoint.get("_data", {})

            # Apply migrations from stored version to current
            migrated_data, new_type = self._apply_migrations(data_dict, type_hint, from_version=version)

            # Reconstruct and return object with potentially new type
            return self.class_registry.construct(new_type, migrated_data)

        # Last resort - try legacy deserializer
        try:
            return self.legacy.loads_typed((type_str or "msgpack", blob))
        except:
            logger.warning(f"Unknown serialization format: {type_str}")
            return {}

    def _apply_migrations(self, data: dict[str, Any], type_hint: str, from_version: int) -> tuple[dict[str, Any], str]:
        """
        Apply all necessary migrations to data.

        This chains migrations from the given version to current.
        Returns both migrated data and potentially updated type hint.
        """
        if from_version >= self.migration_registry.current_version:
            # Already at current version
            return data, type_hint

        result = data.copy()
        current_type = type_hint

        # Get and apply migrations in order
        migrations_needed = self.migration_registry.get_migrations_needed(from_version)

        for migration_class in migrations_needed:
            try:
                # Instantiate and apply migration
                migration = migration_class()
                result, current_type = migration.migrate_data(result, current_type)

            except Exception as e:
                logger.warning(f"Migration {migration_class.__name__} failed: {e}")
                # Continue with other migrations

        return result, current_type
