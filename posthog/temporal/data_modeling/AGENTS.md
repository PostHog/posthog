# Data-modeling Temporal workflows

Temporal workflows and activities that materialize data-modeling saved queries.
v2 is the only backend, and the only one there has ever been in this tree since v1 was deleted.

## Layout

- `workflows/materialize_view.py` materializes one saved query.
- `workflows/execute_dag.py` runs a DAG, or a tier's subset of its nodes.
- Activities in `activities/*.py`.
- Node `run` starts `data-modeling-execute-dag`. Node `materialize` and saved-query `run` start
  `data-modeling-materialize-view` through `start_node_materialization`.

## The retired v1 backend

`run_workflow.py` and the `data-modeling-run` per-query schedules it served are gone. Deleting
the workflow type had to come last: a schedule pointing at a deregistered type does not fail
loudly, it keeps firing, fails its workflow task, and writes no job row. So the type was
deregistered only once both regions held zero `data-modeling-run` schedules.

Two artifacts of v1 survive on purpose. `resolve_log_source` still parses the v1 workflow id
shape, or every pre-cutover run loses its logs; and the v1 `DataModelingJob` rows are the only
record of what ran before the cutover.

## Scoping

- `products/data_warehouse/` is owned by another team, but the saved-query surface in it
  (`presentation/views/saved_query.py` and `logic/data_load/saved_query_service.py`) is data
  modeling's to change. Anything else under that tree needs their review.
- `DataModelingJob` lives in `products/data_modeling/backend/models/`. Only its viewset is
  still under `products/data_warehouse/`.
