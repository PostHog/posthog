import logging
import json
import dataclasses
import importlib
from django.conf import settings
from typing import Any, Optional
from langgraph.checkpoint.serde.base import SerializerProtocol
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from .context import CheckpointContext
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
    _context: Optional[CheckpointContext] = None
    _was_migrated: bool = False

    def __init__(self, context: Optional[CheckpointContext] = None):
        # For reading legacy msgpack data
        self.legacy = JsonPlusSerializer()

        self.migration_registry = migration_registry
        self.class_registry = class_registry

        if not settings.TEST and not context:
            raise ValueError("Context is required")

        self._context = context
        self._was_migrated = False

    @property
    def was_migrated(self) -> bool:
        """Check if the last loads_typed call resulted in a migration."""
        return self._was_migrated

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

            # Create versioned checkpoint for Pydantic objects
            checkpoint = {
                "_type": type_hint,
                "_version": self.migration_registry.current_version,
                "_data": data,
            }
            return (self.DATA_TYPE, json.dumps(checkpoint, default=str).encode("utf-8"))
        else:
            # For non-Pydantic objects (including lists), prepare them first
            # to handle nested Pydantic objects properly
            prepared_obj = self._prepare_nested_value(obj)
            return (self.DATA_TYPE, json.dumps(prepared_obj).encode("utf-8"))

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
                # Include all fields, including None values, to maintain full state
                result[field_name] = self._prepare_nested_value(value)

            return result
        else:
            return obj

    def _prepare_nested_value(self, value: Any) -> Any:
        """
        Recursively prepare nested values for serialization.
        """
        # Check for Pydantic models first (before dict check)
        if hasattr(value, "model_dump"):
            return self._prepare_for_serialization(value)

        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            # Handle dataclasses (like langgraph's Interrupt)
            result: dict[str, Any] = {"_type": value.__class__.__name__, "_module": value.__class__.__module__}  # type: ignore[unreachable]
            # Manually process each field to preserve type information for nested objects
            for field in dataclasses.fields(value):
                field_value = getattr(value, field.name)
                result[field.name] = self._prepare_nested_value(field_value)
            return result

        if isinstance(value, list):
            return [
                self._prepare_for_serialization(item)
                if hasattr(item, "model_dump")
                else self._prepare_nested_value(item)
                for item in value
            ]

        if isinstance(value, tuple):
            # Serialize tuples as lists with a special marker
            return {
                "_tuple": True,
                "items": [
                    self._prepare_for_serialization(item)
                    if hasattr(item, "model_dump")
                    else self._prepare_nested_value(item)
                    for item in value
                ],
            }

        if isinstance(value, dict):
            return {
                k: self._prepare_for_serialization(v) if hasattr(v, "model_dump") else self._prepare_nested_value(v)
                for k, v in value.items()
            }

        return value

    def _reconstruct_nested_value(self, value: Any) -> Any:
        """
        Recursively reconstruct nested Pydantic objects from their serialized form.
        """
        if isinstance(value, list):
            return [self._reconstruct_nested_value(item) for item in value]
        elif isinstance(value, dict):
            # Check if it's a serialized tuple
            if "_tuple" in value and value["_tuple"] is True:
                items = value.get("items", [])
                return tuple(self._reconstruct_nested_value(item) for item in items)
            elif "_type" in value:
                type_hint = value["_type"]

                # Check if it's a dataclass (has _module)
                if "_module" in value:
                    # This is a serialized dataclass
                    module_name = value["_module"]
                    # Remove metadata fields
                    data = {k: v for k, v in value.items() if k not in ["_type", "_module"]}
                    # Recursively reconstruct nested objects
                    for key, val in data.items():
                        data[key] = self._reconstruct_nested_value(val)

                    # Try to import and construct the dataclass
                    try:
                        module = importlib.import_module(module_name)
                        cls = getattr(module, type_hint)
                        return cls(**data)
                    except (ImportError, AttributeError):
                        # If we can't reconstruct it, return the data dict
                        return data
                else:
                    # This is a serialized Pydantic object
                    # Remove the _type field before reconstruction
                    data = {k: v for k, v in value.items() if k != "_type"}
                    # Recursively reconstruct nested objects
                    for key, val in data.items():
                        data[key] = self._reconstruct_nested_value(val)
                    # Construct the object
                    return self.class_registry.construct(type_hint, data)
            else:
                # Regular dict - recursively process its values
                return {k: self._reconstruct_nested_value(v) for k, v in value.items()}
        else:
            return value

    def loads_typed(self, data: tuple[Optional[str], bytes]) -> Any:
        """
        Deserialize with automatic migration.

        This is where the magic happens - old data is automatically
        migrated to the current version.
        """
        type_str, blob = data
        self._was_migrated = False  # Reset migration flag

        # Handle legacy msgpack format
        if type_str in ["msgpack", None, "null", "", "empty"]:
            # Special case: null type with empty blob should return None
            if type_str == "null" and not blob:
                return None

            # Use legacy deserializer
            if not type_str or type_str in ["null", "empty"]:
                type_str = "msgpack"

            try:
                legacy_obj = self.legacy.loads_typed((type_str, blob))

                # Mark that we migrated from legacy format (msgpack to json)
                self._was_migrated = True

                # If it's a state object, also apply migrations
                if hasattr(legacy_obj, "__class__") and hasattr(legacy_obj, "model_dump"):
                    # Convert to dict for migration
                    obj_data = legacy_obj.model_dump()
                    type_hint = legacy_obj.__class__.__name__

                    migrated_data, new_type = self._apply_migrations(obj_data, type_hint, from_version=0)

                    # Reconstruct with migrated data and potentially new type
                    return self.class_registry.construct(new_type, migrated_data)

                # Not a state object, return as-is (but still migrated from msgpack)
                return legacy_obj

            except Exception as e:
                logger.warning(f"Failed to deserialize legacy {type_str}: {e}")
                return {}

        # Handle our versioned format
        if type_str == self.DATA_TYPE:
            decoded = blob.decode("utf-8")
            checkpoint = json.loads(decoded)

            if checkpoint is None:
                return None

            # Check if this is a versioned checkpoint or plain JSON
            if isinstance(checkpoint, dict) and "_type" in checkpoint and "_version" in checkpoint:
                # Extract components from versioned checkpoint
                type_hint = checkpoint.get("_type", "unknown")
                # Ensure version is an integer
                version = checkpoint.get("_version", 0)
                try:
                    version = int(version) if version is not None else 0
                except (ValueError, TypeError):
                    version = 0  # Default to 0 for invalid versions
                data_dict = checkpoint.get("_data", {})

                # Apply migrations from stored version to current
                migrated_data, new_type = self._apply_migrations(data_dict, type_hint, from_version=version)

                # Track if we actually migrated (version was old)
                if version < self.migration_registry.current_version:
                    self._was_migrated = True

                # Reconstruct and return object with potentially new type
                return self.class_registry.construct(new_type, migrated_data)
            else:
                # Plain JSON object - reconstruct any nested Pydantic objects
                return self._reconstruct_nested_value(checkpoint)

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
                result, current_type = migration.migrate_data(result, current_type, self._context)

            except Exception as e:
                logger.warning(f"Migration {migration_class.__name__} failed: {e}")
                # Continue with other migrations

        return result, current_type
