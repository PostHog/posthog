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

## Commits and Pull Requests

Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) for all commit messages and PR titles.

### Commit types

- `feat`: New feature or functionality (touches production code)
- `fix`: Bug fix (touches production code)
- `chore`: Non-production changes (docs, tests, config, CI, refactoring agents instructions, etc.)

### Format

```text
<type>(<scope>): <description>
```

Examples:

- `feat(insights): add retention graph export`
- `fix(cohorts): handle empty cohort in query builder`
- `chore(ci): update GitHub Actions workflow`
- `chore: update AGENTS.md instructions`

### Rules

- Scope is optional but encouraged when the change is specific to a feature area
- Description should be lowercase and not end with a period
- Keep the first line under 72 characters

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

## Security

### SQL Security

- **Never** use f-strings with user-controlled values in SQL queries - this creates SQL injection vulnerabilities
- Use parameterized queries for all VALUES: `cursor.execute("SELECT * FROM t WHERE id = %s", [id])`
- Table/column names from Django ORM metadata (`model._meta.db_table`) are trusted sources
- For ClickHouse identifiers, use `escape_clickhouse_identifier()` from `posthog/hogql/escape_sql.py`
- When raw SQL is necessary with dynamic table/column names:

  ```python
  # Build query string separately from execution, document why identifiers are safe
  table = model._meta.db_table  # Trusted: from Django ORM metadata
  query = f"SELECT COUNT(*) FROM {table} WHERE team_id = %s"
  cursor.execute(query, [team_id])  # Values always parameterized
  ```

### HogQL Security

HogQL queries use `parse_expr()`, `parse_select()`, and `parse_order_expr()`. Two patterns exist:

**Vulnerable pattern** - User data interpolated INTO a HogQL template:

```python
# User data embedded in f-string - can escape context!
parse_expr(f"field = '{self.query.value}'")  # VULNERABLE
```

**Safe patterns**:

```python
# User provides ENTIRE expression - no context to escape
parse_expr(self.query.expression)  # SAFE - HogQL parser validates syntax

# User data wrapped in ast.Constant placeholder
parse_expr("{x}", placeholders={"x": ast.Constant(value=self.query.field)})  # SAFE
```

**Why direct pass-through is safe**: When users provide the entire HogQL expression (not data embedded in a template), there's no string context to escape from. The HogQL parser validates syntax and rejects malformed input.

**Sanitizers** (for use in placeholders):

- `ast.Constant(value=...)` - wraps values safely
- `ast.Tuple(exprs=...)` - for lists of values

### Semgrep Rules

Run `semgrep --config .semgrep/rules/hogql-no-fstring.yaml .` to check for HogQL injection issues.

Two rules:

1. `hogql-injection-taint` - Flags user data (`self.query.*`, etc.) interpolated into f-strings passed to parse functions (HIGH confidence)
2. `hogql-fstring-audit` - Flags all f-strings in parse functions for manual review (LOW confidence)

**When semgrep flags your code:**

- If user data is interpolated into f-string → wrap with `ast.Constant()` in placeholders
- If f-string uses safe values (loop index, enum, dict lookup) → add `# nosemgrep: <rule-id>` with explanation

**Running tests:**

```bash
# Local install
semgrep --test .semgrep/rules/

# Or via Docker
docker run --rm -v "${PWD}:/src" semgrep/semgrep semgrep --test /src/.semgrep/rules/
```

## Important rules for Code Style

- Python: Use type hints, follow mypy strict rules
- Frontend: TypeScript required, explicit return types
- Frontend: If there is a kea logic file, write all business logic there, avoid React hooks at all costs.
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
