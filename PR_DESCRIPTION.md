## Problem

The current LangGraph checkpoint system has a critical limitation: it cannot handle schema evolution. When state models change (new fields, renamed fields, changed types), existing checkpoints stored in the database become unloadable, causing failures when users try to resume conversations.

The root cause is the use of msgpack serialization with `JsonPlusSerializer`, which stores entire Pydantic model instances including their module paths and class definitions. This creates a tight coupling between stored data and the exact code version that created it. Any change to the state schema breaks backward compatibility.

This is particularly problematic for:
- Adding new required fields to state models
- Renaming or restructuring existing fields
- Changing field types or nested structures
- Refactoring class names or module paths
- Evolving the assistant's capabilities over time

Without a migration system, we're forced to either:
1. Never change state schemas (limiting product evolution)
2. Manually migrate database records (risky and not scalable)
3. Accept that old conversations break (poor user experience)

## Changes

This PR implements a comprehensive versioned checkpoint serialization system with automatic migration support. The solution allows state schemas to evolve freely while maintaining full backward compatibility with existing checkpoints.

### Core Components Added

1. **CheckpointSerializer** (`serializer.py`)
   - Replaces msgpack with versioned JSON format
   - Stores simple data dictionaries with type hints instead of full Pydantic models
   - Automatically detects and converts legacy msgpack checkpoints
   - Applies migrations during deserialization to transform old data to current schema

2. **Migration Framework** (`migrations/`)
   - `BaseMigration`: Abstract base class for writing data transformations
   - `MigrationRegistry`: Manages ordered application of migrations
   - Migrations are pure functions that transform data dictionaries
   - Supports field additions, renames, type changes, and class renames
   - Example migration included demonstrating the pattern

3. **ClassRegistry** (`class_registry.py`)
   - Auto-discovers Pydantic classes from configured modules
   - Eliminates hardcoded module paths in stored data
   - Provides type-safe reconstruction of nested Pydantic objects
   - Gracefully handles unknown types by returning dictionaries

4. **Updated DjangoCheckpointer** (`checkpointer.py`)
   - Modified to use new `CheckpointSerializer` instead of `JsonPlusSerializer`
   - Maintains exact same LangGraph API for compatibility
   - All existing functionality preserved

### How It Works

**Writing checkpoints (no change to API):**
1. Pydantic model is serialized to a data dictionary
2. Type hints and version metadata are added
3. Data is stored as JSON (human-readable, debuggable)

**Reading checkpoints (automatic migration):**
1. System detects format (JSON or legacy msgpack)
2. For legacy data: converts to new format, treats as version 0
3. For versioned data: reads stored version number
4. Applies all migrations from stored version to current
5. Reconstructs Pydantic models with migrated data

**Creating migrations (simple Python functions):**
```python
class Migration0002(BaseMigration):
    def migrate_data(self, data: dict, type_hint: str) -> tuple[dict, str]:
        if type_hint == "AssistantState" and "new_field" not in data:
            data["new_field"] = "default_value"
        return data, type_hint
```

### Benefits

- **Full backward compatibility**: All existing checkpoints continue to work
- **Schema evolution**: State models can now change freely over time
- **Zero downtime**: Migrations run automatically during deserialization
- **Better debugging**: JSON format is human-readable vs binary msgpack
- **Testable**: Pure function migrations are easy to unit test
- **Maintainable**: Clear separation between serialization, migration, and reconstruction

### Documentation

- `SYSTEM_ARCHITECTURE.md`: Comprehensive overview of the architecture and design decisions
- `MIGRATION_GUIDE.md`: Step-by-step guide for creating and testing migrations

## How did you test this code?

### Unit Tests

- **Serializer Tests** (`test_serializer.py`)
  - Round-trip serialization/deserialization of state objects
  - Conversion of legacy msgpack data to new format
  - Application of migrations during deserialization
  - Handling of nested Pydantic objects
  - Error cases and edge conditions

- **Migration Registry Tests** (`test_migration_registry.py`)
  - Version extraction from migration filenames
  - Correct ordering of migration application
  - Migration chain from old versions to current

- **Class Registry Tests** (`test_class_registry.py`)
  - Auto-discovery of Pydantic classes
  - Reconstruction of objects by name
  - Handling of unknown types
  - Nested object reconstruction

### Integration Tests

- **Checkpointer Integration** (`test_checkpointer_integration.py`)
  - Full checkpoint save/load cycle with new serializer
  - Compatibility with LangGraph's checkpoint interface
  - Transaction handling and atomicity
  - Channel values and pending writes

- **Legacy Fixtures** (`test_legacy_fixtures.py`)
  - Real msgpack checkpoints from production load correctly
  - Automatic conversion to new format preserves all data
  - Migrations apply correctly to legacy data

- **End-to-End LangGraph** (`test_e2e_langgraph.py`)
  - Complete LangGraph workflow with checkpointing
  - State persistence across graph interruptions
  - Migration of old graph states to new schema

### Manual Testing

1. Created checkpoints with old code (msgpack format)
2. Deployed new code and verified old checkpoints load
3. Modified state schema and created migration
4. Verified old checkpoints automatically migrate to new schema
5. Tested various migration scenarios (field additions, renames, restructuring)
6. Verified no performance degradation in checkpoint operations

### Test Coverage

All new code has comprehensive test coverage including:
- Happy paths for all components
- Edge cases and error conditions
- Legacy compatibility scenarios
- Migration chaining scenarios
- Concurrent access patterns