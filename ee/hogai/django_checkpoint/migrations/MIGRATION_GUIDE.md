# LangGraph Checkpoint Migration System

## Overview

The migration system provides automatic schema evolution for Max AI LangGraph-based checkpoint data. Migrations are applied online when checkpoints are accessed.

## Architecture

### Version Inference
Migration versions are inferred from filenames:
- `_0001_add_version_metadata.py` → version 1
- `_0002_some_migration.py` → version 2

## Graph Types and Contexts
GraphType and GraphContext are used by migrations to determine which changes to apply, to which states.
You can extend these enums with new types. If any of these types becomes deprecated, add a # DEPRECATED comment next to it.
*DO NOT REMOVE* types from these enums, or migrations will break.

```python
class GraphType(Enum):
    ASSISTANT = "assistant"
    INSIGHTS = "insights"
    FILTER_OPTIONS = "filter_options"

class GraphContext(Enum):
    ROOT = "root"           # Independent execution
    SUBGRAPH = "subgraph"   # Part of another graph
```

## Graph Integration

### BaseAssistantGraph
Graphs automatically configure checkpointers.
When instantiating a graph, you can override `context` to specify how the graph is being used.

```python
class BaseAssistantGraph(Generic[StateType]):
    def __init__(self, team, user, state_type, graph_type: GraphType, context: GraphContext):
        self._graph_type = graph_type
        self._context = context
        
    def compile(self, checkpointer=None):
        if checkpointer is None:
            checkpointer = DjangoCheckpointer(self._graph_type, self._context)
```

### Subgraph Support
```python
def add_subgraph(self, node_name, subgraph_class, graph_type: GraphType):
    subgraph_checkpointer = DjangoCheckpointer(graph_type, GraphContext.SUBGRAPH)
    compiled_subgraph = subgraph_instance.compile(checkpointer=subgraph_checkpointer)
```

### DjangoCheckpointer Integration
The checkpointer requires graph type and context for migration routing:
```python
checkpointer = DjangoCheckpointer(GraphType.ASSISTANT, GraphContext.ROOT)
```

When the Checkpointer reads checkpoints (`alist` method), it tries to apply all available migrations to the the Checkpoint and related CheckpointBlob and CheckpointBlob. A `VersionMetadata` object is added to the state under `version_metadata`
When creating (`awrite`) or updating (`aput`) a checkpoint, it adds the current `VersionMetadata`.

## Version Metadata

States include optional version metadata:
```python
class VersionMetadata(BaseModel):
    schema_version: int        # Current migration version
    migrated_at: str          # ISO timestamp
    graph_type: GraphType     # Graph type for routing
    context: GraphContext     # Execution context
```
Version metadata is optional only to support legacy data. It should be available in all states migrated after migration 0001.

## Registry

The registry manages migration ordering:
```python
registry = MigrationRegistry()

# Register migrations
registry.register_migration(Migration0001)

# Get current version
registry.current_version  # Highest registered migration

# Get needed migrations
registry.get_migrations_needed(from_version=0)  # Returns [Migration0001, ...]
```

## Creating New Migrations

1. Create file: `ee/hogai/django_checkpoint/migrations/_NNNN_description.py`
2. Implement migration class
3. Register at module end:
```python
from .registry import registry
registry.register_migration(MyMigration)
```

## Migration Types

### Base Migration Class

All migrations inherit from `BaseMigration`:
```python
class BaseMigration(ABC):
    @classmethod
    def get_version(cls) -> int:
        """Version from filename via registry"""
        return registry.get_version_for_class(cls)
    
    @staticmethod
    @abstractmethod
    def needs_migration(state_obj: Any) -> bool:
        """Check if migration needed"""
    
    @staticmethod
    @abstractmethod
    def apply_to_state_object(
        state_obj: Any, 
        graph_type: GraphType, 
        context: GraphContext
    ) -> Any:
        """Transform state object"""
    
    @classmethod
    async def apply_to_blob_or_write(cls, object, serde, graph_type, context):
        """Apply migration to blob/write (common implementation)"""
    
    @classmethod
    async def apply_to_checkpoint(cls, checkpoint, serde, graph_type, context):
        """Orchestrate migration of entire checkpoint"""
```

### Custom Migrations
Migration 0001 adds version metadata to legacy states:
```python
class Migration0001(BaseMigration):
    @staticmethod
    def needs_migration(state_obj: Any) -> bool:
        # Check if state lacks version_metadata
        if hasattr(state_obj, 'version_metadata'):
            return state_obj.version_metadata is None
        # Check dict-based states
        if isinstance(state_obj, dict):
            if 'version_metadata' in state_obj:
                return False
            # Check for state indicators
            state_indicators = {'messages', 'plan', 'current_filters', ...}
            return bool(state_indicators.intersection(state_obj.keys()))
```
