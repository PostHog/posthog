# Data-modeling Temporal workflows

Temporal workflows and activities that materialize data-modeling saved queries.
v2 is the only backend. The v1 code stays registered until its schedules are removed.

## v1 — dead, pending removal

- `run_workflow.py` (1814-line monolith).
- Node and saved-query interactive paths always start v2. No production or management-command
  call site creates a `data-modeling-run` schedule. Endpoint compatibility paths can still trigger
  a pre-existing schedule until the v1 control cleanup lands.
- `RunWorkflow` stays in `WORKFLOWS` (`__init__.py`) on purpose. A schedule that points at a
  deregistered workflow type keeps firing, fails its workflow task, and writes no job row, so
  the workflow can only be removed after its schedules are gone.

**Do not extend v1.** No new features, no refactors, no new error types.
The v1 code exists only until its schedules are removed.

## v2 — active

- `workflows/materialize_view.py` and `workflows/execute_dag.py`.
- Activities in `activities/*.py`.
- Node `run` starts `data-modeling-execute-dag`. Node `materialize` and saved-query `run` start
  `data-modeling-materialize-view` through `start_node_materialization`.

All new work targets v2: new activities, new error types, configuration knobs,
reliability fixes, and tests.

## Scoping

- `products/data_warehouse/` is owned by another team. Read-only from here —
  do not modify code under that tree without their review.
- `DataModelingJob` currently lives in `products/data_warehouse/` for historical
  reasons; It will soon be moved to `products/data_modeling/`.
