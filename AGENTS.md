# PostHog Development Guide

## Commands

- Environment:
    - Auto-detect flox environment before running terminal commands
    - If flox is available, and you run into trouble executing commands, try with `flox activate -- bash -c "<command>"` pattern
        - Never use `flox activate` in interactive sessions (it hangs if you try)
- Tests:
    - All tests: `pytest`
    - Single test: `pytest path/to/test.py::TestClass::test_method`
    - Frontend: `pnpm --filter=@posthog/frontend test`
    - Single frontend test: `pnpm --filter=@posthog/frontend jest <test_file>`
- Lint:
    - Python:
        - `ruff check . --fix` and `ruff format .`
        - Do not run mypy for type checks. It takes too long.
    - Frontend: `pnpm --filter=@posthog/frontend format`
    - TypeScript check: `pnpm --filter=@posthog/frontend typescript:check`
- Build:
    - Frontend: `pnpm --filter=@posthog/frontend build`
    - Start dev: `./bin/start`

## ClickHouse Migrations

### Migration structure

```python
operations = [
    run_sql_with_exceptions(
        SQL_FUNCTION(),
        node_roles=[...],
        sharded=False,  # True for sharded tables
        is_alter_on_replicated_table=False  # True for ALTER on replicated tables
    ),
]
```

### Node roles (choose based on table type)

- `[NodeRole.DATA]`: Sharded tables (data nodes only)
- `[NodeRole.DATA, NodeRole.COORDINATOR]`: Non-sharded data tables, distributed read tables, replicated tables, views, dictionaries
- `[NodeRole.INGESTION_SMALL]`: Writable tables, Kafka tables, materialized views on ingestion layer

### Table engines quick reference

MergeTree engines:

- `AggregatingMergeTree(table, replication_scheme=ReplicationScheme.SHARDED)` for sharded tables
- `ReplacingMergeTree(table, replication_scheme=ReplicationScheme.REPLICATED)` for non-sharded
- Other variants: `CollapsingMergeTree`, `ReplacingMergeTreeDeleted`

Distributed engine:

- Sharded: `Distributed(data_table="sharded_events", sharding_key="sipHash64(person_id)")`
- Non-sharded: `Distributed(data_table="my_table", cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER)`

### Critical rules

- NEVER use `ON CLUSTER` clause in SQL statements
- Always use `IF EXISTS` / `IF NOT EXISTS` clauses
- When dropping and recreating replicated table in same migration, use `DROP TABLE IF EXISTS ... SYNC`
- If a function generating SQL has on_cluster param, always set `on_cluster=False`
- Use `sharded=True` when altering sharded tables
- Use `is_alter_on_replicated_table=True` when altering non-sharded replicated tables

### Testing

Delete entry from `infi_clickhouse_orm_migrations` table to re-run a migration

### Detailed documentation

See `posthog/clickhouse/migrations/AGENTS.md` for comprehensive patterns, examples, and ingestion layer setup

## Important rules for Code Style

- Python: Use type hints, follow mypy strict rules
- Frontend: TypeScript required, explicit return types
- Imports: Use prettier-plugin-sort-imports (automatically runs on format), avoid direct dayjs imports (use lib/dayjs)
- CSS: Use tailwind utility classes instead of inline styles
- Error handling: Prefer explicit error handling with typed errors
- Naming: Use descriptive names, camelCase for JS/TS, snake_case for Python
- Comments: should not duplicate the code below, don't tell me "this finds the shortest username" tell me _why_ that is important, if it isn't important don't add a comment, almost never add a comment
- Python tests: do not add doc comments
- jest tests: when writing jest tests, prefer a single top-level describe block in a file
- any tests: prefer to use parameterized tests, think carefully about what input and output look like so that the tests exercise the system and explain the code to the future traveller
- Python tests: in python use the parameterized library for parameterized tests, every time you are tempted to add more than one assertion to a test consider (really carefully) if it should be a parameterized test instead
- always remember that there is a tension between having the fewest parts to code (a simple system) and having the most understandable code (a maintainable system). structure code to balance these two things.
- Separation of concerns: Keep different responsibilities in different places (data/logic/presentation, safety checks/policies, etc.)
- Reduce nesting: Use early returns, guard clauses, and helper methods to avoid deeply nested code
- Avoid over-engineering: Don't apply design patterns just because you know them
- Start simple, iterate: Build minimal solution first, add complexity only when demanded

## General

- Use American English spelling
- When mentioning PostHog products, the product names should use Sentence casing, not Title Casing. For example, 'Product analytics', not 'Product Analytics'. Any other buttons, tab text, tooltips, etc should also all use Sentence casing. For example, 'Save as view' instead of 'Save As View'.
