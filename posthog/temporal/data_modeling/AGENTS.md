# Data-modeling Temporal workflows

Temporal workflows and activities that materialize data-modeling saved queries.
Two implementations live here side by side during the v1 → v2 migration.

## v1 — FROZEN

- `run_workflow.py` (1814-line monolith).
- Dispatched from `products/data_modeling/backend/api/node.py` when
  `_is_v2_backend_enabled(...)` is false.
- Almost all US teams are still on v1; almost all EU teams are on v2.

**Do not extend v1.** No new features, no refactors, no new error types.
Bug fixes that affect both versions can land here, but treat that as the
exception — the goal is to keep the migration window small.

## v2 — active

- `workflows/materialize_view.py` and `workflows/execute_dag.py`.
- Activities in `activities/*.py`.
- Dispatched when `_is_v2_backend_enabled(...)` is true.

All new work targets v2: new activities, new error types, configuration knobs,
reliability fixes, and tests.

## Scoping

- `products/data_warehouse/` is owned by another team. Read-only from here —
  do not modify code under that tree without their review.
- `DataModelingJob` currently lives in `products/data_warehouse/` for historical
  reasons; It will soon be moved to `products/data_modeling/`.
