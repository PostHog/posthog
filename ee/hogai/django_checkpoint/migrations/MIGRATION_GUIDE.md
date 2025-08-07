# Checkpoint Data Migration Guide

## Introduction

This guide explains how to create and manage data migrations for the Django checkpoint system. Migrations allow you to evolve your LangGraph state schemas over time while maintaining compatibility with existing checkpoints stored in the database.

## Understanding the Migration System

### What Are Checkpoint Migrations?

Checkpoint migrations are Python functions that transform stored checkpoint data from one schema version to another. Unlike Django database migrations, these migrations:

- Only transform data structures, never touch the database
- Run automatically during checkpoint deserialization
- Are pure functions with no side effects
- Can be chained together to migrate through multiple versions

### When Do You Need a Migration?

Create a migration when you:

- Add new required fields to a state model
- Remove or rename existing fields
- Change field types or structures
- Rename state classes
- Restructure nested data
- Split or merge state models

### How Migrations Are Applied

1. User requests a checkpoint from the database
2. System reads the `_version` field from stored data
3. System determines which migrations need to run
4. Migrations run in order (e.g., 1→2→3)
5. Final data is used to construct Pydantic models

## Creating Your First Migration

### Step 1: Create the Migration File

Create a new file in `ee/hogai/django_checkpoint/migrations/` with the naming pattern:
```
_NNNN_description.py
```

Where:
- `NNNN` is a 4-digit number (e.g., `0002`)
- `description` is a brief description (e.g., `add_user_context`)

Example: `_0002_add_user_context.py`

### Step 2: Write the Migration Class

```python
from typing import Any
import logging
from ee.hogai.django_checkpoint.serializer import CheckpointContext
from ee.hogai.django_checkpoint.migrations.base import BaseMigration
from ee.hogai.django_checkpoint.migrations.migration_registry import migration_registry

logger = logging.getLogger(__name__)

class Migration0002AddUserContext(BaseMigration):
    """
    Add user_context field to AssistantState with empty dict default.
    """
    
    def migrate_data(self, data: dict[str, Any], type_hint: str, context: CheckpointContext) -> tuple[dict[str, Any], str]:
        # Only apply to AssistantState objects
        if type_hint == "AssistantState":
            # Add new field if it doesn't exist
            if "user_context" not in data:
                data["user_context"] = {}
                logger.info("Added user_context field to AssistantState")
        
        return data, type_hint

# Register the migration
migration_registry.register_migration(Migration0002AddUserContext)
```

## Common Migration Patterns

### Adding a New Field with Default Value

```python
def migrate_data(self, data: dict[str, Any], type_hint: str, context: CheckpointContext) -> tuple[dict[str, Any], str]:
    if type_hint == "AssistantState":
        # Add field with default value
        if "foo" not in data:
            data["foo"] = "bar"
    
    return data, type_hint
```

### Renaming a Field

```python
def migrate_data(self, data: dict[str, Any], type_hint: str, context: CheckpointContext) -> tuple[dict[str, Any], str]:
    if type_hint == "AssistantState":
        # Rename old_field to new_field
        if "old_field" in data:
            data["new_field"] = data.pop("old_field")
    
    return data, type_hint
```

### Changing Field Structure

```python
def migrate_data(self, data: dict[str, Any], type_hint: str, context: CheckpointContext) -> tuple[dict[str, Any], str]:
    if type_hint == "AssistantState":
        # Convert string to list
        if isinstance(data.get("tags"), str):
            data["tags"] = [data["tags"]]
        
        # Convert flat structure to nested
        if "user_name" in data and "user_email" in data:
            data["user"] = {
                "name": data.pop("user_name"),
                "email": data.pop("user_email")
            }
    
    return data, type_hint
```

### Renaming a Class

```python
def migrate_data(self, data: dict[str, Any], type_hint: str, context: CheckpointContext) -> tuple[dict[str, Any], str]:
    # Rename OldAssistantState to AssistantState
    if type_hint == "OldAssistantState":
        type_hint = "AssistantState"
    
    # Also update any nested type hints
    if data.get("_type") == "OldAssistantState":
        data["_type"] = "AssistantState"
    
    return data, type_hint
```

### Handling Nested Objects

```python
def migrate_data(self, data: dict[str, Any], type_hint: str, context: CheckpointContext) -> tuple[dict[str, Any], str]:
    if type_hint == "AssistantState":
        # Migrate nested messages
        messages = data.get("messages", [])
        for message in messages:
            if isinstance(message, dict):
                # Add timestamp to old messages
                if "timestamp" not in message:
                    message["timestamp"] = "2024-01-01T00:00:00Z"
    
    return data, type_hint
```

### Using the CheckpointContext

```python
def migrate_data(self, data: dict[str, Any], type_hint: str, context: CheckpointContext) -> tuple[dict[str, Any], str]:
    if context.thread_type = Conversation.Type.TOOL_CALL and context.graph_context == GraphContext.SUBGRAPH:
        # Do something that only applies to subgraphs in tool calls
    
    return data, type_hint
```
