# Entity dependencies

A registry of references between entities across products: "workflow X targets cohort 123", "flag Y filters on cohort 123". Each reference is a row in `posthog_entitydependency`, keyed by stable string entity types and string ids, so it can answer "what references this?" in one indexed query without walking JSON at read time.

## The contract

- A row describes what the **source** says, not the state of the **target**. Whether the target exists, is deleted, or has changed shape is resolved at read time by looking at the target.
- Rows are derived data. `sync_dependencies` recomputes the full set for one source from the source instance and diffs it against what is stored, so a sync is idempotent and any source can be rebuilt at any time.
- Products own their semantics. Core stores, syncs, and lists rows. It never imports product models: a product registers a `DependencySource` under an `entity_type` string, and core calls it through the registry.
- Rows are team-scoped through the fail-closed `TeamScopedManager` (`posthog/models/scoping/README.md`). Outside request context, read with `EntityDependency.objects.for_team(team_id)`.

## Registering a source

A source is a model that holds references to other entities. Implement `DependencySource` next to the product and register it once at app-ready time:

```python
# products/<name>/backend/entity_dependencies.py
from posthog.models.entity_dependencies.registry import DependencySource, register_source
from posthog.models.entity_dependencies.types import Reference


class HogFlowDependencySource(DependencySource[HogFlow]):
    entity_type = "hog_flow"
    model = HogFlow

    def extract_references(self, instance: HogFlow) -> list[Reference]:
        if instance.status == HogFlow.State.ARCHIVED:
            return []
        return [
            Reference(target_type="cohort", target_id=str(cohort_id), role="trigger_audience", path="trigger")
            for cohort_id in cohort_ids_in(instance.trigger)
        ]


register_source(HogFlowDependencySource())
```

`register_source` connects `post_save` and `post_delete` on the model, so rows follow every `save()` and `delete()`. `extract_references` must be a pure function of the instance. Return `[]` for an instance the product considers gone (soft-deleted, archived): the diff removes its rows, and a later restore recreates them.

`role` is a source-defined label for where the reference sits. `path` locates the reference inside the source and is part of a row's identity, so two occurrences of the same target in the same role are both kept.

## Write paths that skip `save()`

`.update()`, `bulk_update`, and raw SQL fire no signals. A write path that changes reference-bearing fields this way must call `sync_instance_dependencies(instance)` itself. Audit a source's write paths when you register it; a source with an unaudited bypass drifts silently.

A sync that fails inside a signal receiver is logged, reported to error tracking, and counted in `entity_dependency_sync_failures_total`, but it does not block the product write. In tests it raises, so an extraction bug fails the product's own test suite instead of hiding.

## Concurrency

`sync_dependencies` runs inside `transaction.atomic()` and takes a transaction-scoped advisory lock keyed by `(source_type, source_id)`. PostHog has no `ATOMIC_REQUESTS`, so this is what serializes two concurrent saves of the same source. When the caller is already in a transaction, the rows commit or roll back together with the source write.
