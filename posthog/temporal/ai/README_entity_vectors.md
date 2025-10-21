# Generic Entity Vectorization System

A unified framework for vectorizing any entity type (actions, cohorts, etc.) without code duplication.

## Architecture

The system uses a **strategy pattern** with three main components:

1. **`EntityConfig`**: Abstract base class defining how to work with an entity type
2. **Entity Implementations**: Concrete configs for each entity (e.g., `ActionEntityConfig`, `CohortEntityConfig`)
3. **Generic Workflow**: Single workflow (`SyncEntityVectorsWorkflow`) that works with any entity

## Using the Generic Workflow

### Example: Vectorize Actions

```python
from posthog.temporal.ai import SyncEntityVectorsInputs

inputs = SyncEntityVectorsInputs(
    domain="action",  # Entity type to vectorize
    start_dt="2025-01-15T00:00:00",  # Optional: defaults to now
    summarize_batch_size=96,
    embed_batch_size=96,
    max_parallel_requests=5,
    insert_batch_size=10000,
    delay_between_batches=60,
    embedding_version=1,
)
```

### Example: Vectorize Cohorts

```python
inputs = SyncEntityVectorsInputs(
    domain="cohort",  # Just change the domain!
    embedding_version=1,
)
```

## Adding a New Entity Type

To add support for a new entity (e.g., "event_definition"), create a config:

```python
# posthog/temporal/ai/entity_configs.py

class EventDefinitionEntityConfig(EntityConfig[EventDefinition]):
    @property
    def domain_name(self) -> str:
        return "event_definition"

    @property
    def model_class(self) -> type[EventDefinition]:
        return EventDefinition

    def get_queryset_filter(self, start_dt: datetime) -> Q:
        return Q(
            team__organization__is_ai_data_processing_approved=True,
            updated_at__lte=start_dt,
        ) & (
            Q(last_summarized_at__isnull=True)
            | Q(updated_at__gte=F("last_summarized_at"))
            | Q(last_summarized_at=start_dt)
        )

    def get_queryset_ordering(self) -> list[str]:
        return ["id", "team_id", "updated_at"]

    async def batch_summarize(
        self, entities: list[EventDefinition], start_dt: str, properties: dict[str, Any]
    ) -> list[str | BaseException]:
        # Implement your summarization logic
        return await abatch_summarize_event_definitions(entities, start_dt=start_dt, properties=properties)

    def get_sync_values_fields(self) -> list[str]:
        return ["team_id", "id", "summary", "name", "description"]

    def build_clickhouse_properties(self, entity_dict: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": entity_dict["name"],
            "description": entity_dict["description"],
        }

    def get_entity_id_field(self) -> str:
        return "event_definition_id"
```

Then register it in `__init__.py`:

```python
from .entity_configs import ActionEntityConfig, CohortEntityConfig, EventDefinitionEntityConfig

register_entity_config(ActionEntityConfig())
register_entity_config(CohortEntityConfig())
register_entity_config(EventDefinitionEntityConfig())  # Add this
```

That's it! The generic workflow will now support your new entity.

## Backward Compatibility

The old workflows (`SyncVectorsWorkflow` for actions, `SyncCohortVectorsWorkflow` for cohorts) are still available and functional. They're kept for backward compatibility but internally could be refactored to use the generic system.

## Benefits

1. **No code duplication**: Write entity-specific logic once in the config
2. **Consistent behavior**: All entities follow the same workflow
3. **Easy to add new entities**: Just create a config and register it
4. **Type-safe**: Uses generics for type checking
5. **Maintainable**: Bug fixes in the workflow apply to all entities

## How It Works

1. **Registration**: Entity configs are registered at startup with `register_entity_config()`
2. **Workflow execution**: The workflow receives a `domain` parameter (e.g., "action", "cohort")
3. **Config lookup**: The workflow looks up the registered config for that domain
4. **Delegation**: All entity-specific operations are delegated to the config

## Running the Workflow

Via Temporal CLI:

```bash
# Actions
temporal workflow start \
  --type ai-sync-entity-vectors \
  --task-queue max-ai-task-queue \
  --input '{"domain": "action", "embedding_version": 1}'

# Cohorts
temporal workflow start \
  --type ai-sync-entity-vectors \
  --task-queue max-ai-task-queue \
  --input '{"domain": "cohort", "embedding_version": 1}'
```

Via management command (if you add one):

```bash
python manage.py run_temporal_workflow ai-sync-entity-vectors \
  --domain action \
  --embedding-version 1
```

## Testing

To test a new entity config:

```python
from posthog.temporal.ai.entity_configs import YourEntityConfig
from posthog.temporal.ai.sync_entity_vectors import register_entity_config

# Register your config
config = YourEntityConfig()
register_entity_config(config)

# Test it
from posthog.temporal.ai import SyncEntityVectorsInputs
inputs = SyncEntityVectorsInputs(domain="your_entity")
# Execute workflow with inputs
```
