# ClickHouse migration tools

Declarative, Terraform-style schema management for ClickHouse.

## Architecture

```text
schema/*.yaml          desired state (what you want)
     |
     v
desired_state.py       parse YAML into DesiredState objects
     |
     v
state_diff.py          diff desired vs current -> list[StateDiff]
     |
     v
plan_generator.py      StateDiff -> human-readable plan + ManifestStep list
     |
     v
runner.py              route each ManifestStep to correct ClickHouse nodes
```

Supporting modules:

- `schema_introspect.py` -- query live ClickHouse for current schema, detect drift
- `schema_graph.py` -- table ecosystem definitions (which tables form a pipeline)
- `tracking.py` -- advisory locking for concurrent apply prevention
- `manifest.py` -- ManifestStep dataclass and node role mapping
- `templates.py` -- generate schema YAML dicts from named templates
- `validator.py` -- lint schema YAML for ecosystem completeness and targeting

## Developer flow

```bash
# Generate schema YAML from a template
python manage.py ch_migrate generate --template ingestion_pipeline --table sessions_v4

# Edit the generated YAML
$EDITOR posthog/clickhouse/schema/sessions_v4.yaml

# Diff desired vs current
python manage.py ch_migrate plan

# Execute the plan
python manage.py ch_migrate apply
```

## Available templates

| Template                 | Objects created                                |
| ------------------------ | ---------------------------------------------- |
| `ingestion_pipeline`     | kafka + sharded + writable + readable + MV (5) |
| `sharded_table`          | sharded + writable + readable (3)              |
| `cross_cluster_readable` | distributed table for cross-cluster reads      |
| `materialized_view`      | single MV                                      |
| `add_column`             | guidance to edit existing YAML directly        |
| `drop_table`             | guidance to remove from existing YAML          |

## Modules

- `desired_state.py` -- parses `schema/*.yaml` into DesiredState objects
- `state_diff.py` -- diffs desired state against live ClickHouse schema
- `plan_generator.py` -- generates human-readable plan + executable SQL steps
- `schema_introspect.py` -- queries `system.tables`/`system.columns` across all hosts
- `schema_graph.py` -- models table ecosystems (events, sessions, person, replay)
- `templates.py` -- generates desired-state YAML from template configs
- `runner.py` -- executes SQL steps via ClickhouseCluster + legacy migration support
- `tracking.py` -- per-host step tracking, advisory locking
- `validator.py` -- validates desired-state YAML (ecosystem completeness, cross-cluster targeting)
- `manifest.py` -- ManifestStep dataclass + node role mapping

## Running tests

```bash
uv run python -m pytest posthog/clickhouse/test/test_reconcile.py -v
uv run python -m pytest posthog/clickhouse/test/test_advisory_lock.py -v
```
