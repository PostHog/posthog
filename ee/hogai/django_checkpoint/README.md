# Django Checkpoint System Architecture

## Overview

This folder contains a implementation for a LangGraph Checkpointer that integrates with Django models, allowing state models to change over time while maintaining backward compatibility with existing checkpoints stored in the database.

## The Problem We're Solving

Previously, the checkpoint system used msgpack serialization with `JsonPlusSerializer`, which stored entire Pydantic model instances including their module paths and class definitions. This approach had several limitations:

1. Schema evolution: When a Pydantic model changed (new fields, renamed fields, changed types), old checkpoints became unloadable
2. Module dependencies: Stored checkpoints were tightly coupled to specific module paths (the `JsonPlusSerializer` would store the paths to the Pydantic classes directly in the checkpoints)
3. No migration path: No mechanism existed to transform old data to new schemas
4. Debugging difficulty: Binary msgpack format made it hard to inspect stored data

## Core Components

### 1. CheckpointSerializer (`serializer.py`)

A custom serializer that replaces `JsonPlusSerializer` with a versioned, migration-aware approach.

- Converts Pydantic models to simple JSON dictionaries with type hints
- Adds version metadata to track schema version
- Applies migrations during deserialization
- Maintains backward compatibility with legacy msgpack format

Serialization flow:
```python
Pydantic Model → Extract data → Add type hint → Add version → JSON encode → Store
```

Deserialization flow:
```python
Read from DB → Detect format → Apply migrations → Reconstruct Pydantic model → Return
```

### 2. ClassRegistry (`class_registry.py`)

An auto-discovery system for Pydantic classes that eliminates hardcoded module paths.

**How it works:**
1. Scans predefined modules at initialization (`ee.hogai.utils.types`, `posthog.schema`)
2. Builds a cache of class name → class type mappings
3. Provides type-safe reconstruction of nested Pydantic objects
4. Falls back gracefully to dictionaries for unknown types

- No hardcoded imports needed in migrations
- Handles nested Pydantic objects recursively
- Graceful degradation for unknown types

### 3. MigrationRegistry (`migrations/migration_registry.py`)

Manages the ordered application of data migrations.

- Maintains ordered list of migrations by version number
- Determines which migrations to apply based on stored version
- Chains migrations sequentially from old version to current
- Extracts version numbers from migration filenames

Version numbering:
- Migrations use `_NNNN_description.py` naming convention
- Version is extracted from filename (e.g., `_0001_` → version 1)
- Current version is the highest registered migration number

### 4. BaseMigration (`migrations/base.py`)

Abstract base class for all data migrations.

Design principles:
- No I/O, no database access
- Idempotent: safe to run multiple times
- Handle missing fields with sensible defaults

Migration interface:
```python
def migrate_data(self, data: dict, type_hint: str, context: CheckpointContext) -> tuple[dict, str]:
    # Transform data
    # Optionally change type_hint for class renames
    return modified_data, new_type_hint
```

See `migrations/MIGRATION_GUIDE.md` for more information.

### 5. DjangoCheckpointer (`checkpointer.py`)

Integrates with LangGraph's checkpoint system using Django models.

Changes from original:
- Uses `CheckpointSerializer` instead of `JsonPlusSerializer`
- Maintains same public API for LangGraph compatibility
- Handles channel values and pending writes with new serializer
- Requires additional context `ContextSerializer` to be passed to the migrations

## Data Storage Format

### New Format (Versioned JSON)
```json
{
  "_type": "AssistantState",
  "_version": 2,
  "_data": {
    "_type": "AssistantState",
    "messages": [...],
    "context": {...}
  }
}
```

### Legacy Format (msgpack)
- Binary encoded Pydantic models with full module paths
- Automatically detected and migrated to new format on read
