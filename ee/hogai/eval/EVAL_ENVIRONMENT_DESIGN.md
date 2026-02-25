# Eval Environment: Postgres Snapshots + Production ClickHouse

## Context

PostHog's AI agent evaluations currently run in isolated Docker containers
with local ClickHouse and Postgres ("offline" mode).
The agent team wants to evaluate Agents SDK (Claude Code SDK) agents
that use MCP servers to query real production data ("online" mode).

The new eval environment needs:

- **Production ClickHouse** (read-only) for event data (events, sessions, persons, groups)
- **AWS Aurora** with per-eval-run databases for Postgres system tables
- Existing Dagster snapshot pipeline already exports Postgres models to Avro in S3

The key technical challenge: HogQL system tables compile to ClickHouse's `postgresql()` function,
which means ClickHouse itself connects to Postgres.
When using production CH, the `postgresql()` calls must point to the Aurora eval database.

**Important**: In online mode, taxonomy queries run live against production CH
(no patching needed, unlike offline mode which precomputes them from snapshots).

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                     Docker Container                         │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐ │
│  │ Agents SDK   │───>│ MCP Server   │───>│ Django App    │ │
│  │ (Claude Code)│    │ (stdio)      │    │ (HogQL+API)  │ │
│  └──────────────┘    └──────────────┘    └───────┬───────┘ │
│                                                  │         │
└──────────────────────────────────────────────────┼─────────┘
                                                   │
                    ┌──────────────────────────────┼──────────────────────┐
                    │                              │                      │
                    ▼                              ▼                      │
        ┌────────────────────┐        ┌────────────────────┐             │
        │ Production CH      │        │ AWS Aurora          │             │
        │ (read-only)        │◄───────│ (eval_run_<id> db)  │             │
        │ events, sessions   │  CH    │ restored snapshots  │             │
        │ persons, groups    │  postgresql()                │             │
        └────────────────────┘        └────────────────────┘             │
                                              ▲                          │
                                              │ Django ORM               │
                                              └──────────────────────────┘
```

### Data flow for a HogQL query like `SELECT * FROM system.cohorts`:

1. Agent calls `execute_sql` MCP tool
2. Django compiles HogQL → CH SQL: `SELECT * FROM postgresql(aurora:5432, eval_db, posthog_cohort, user, pass)`
3. Query sent to production ClickHouse
4. CH executes the `postgresql()` function, connecting to Aurora to read the table
5. Results returned through the chain

### Data flow for a HogQL query like `SELECT * FROM events`:

1. Agent calls `execute_sql` MCP tool
2. Django compiles HogQL → CH SQL: `SELECT * FROM events WHERE team_id = X`
3. Query sent to production ClickHouse
4. CH reads from its own event tables
5. Results returned through the chain

## Implementation Steps

### Step 1: Modify `build_function_call()` to prefer RDSPROXY env vars

**File**: `posthog/hogql/database/postgres_table.py`

Currently the function checks `settings.DEBUG or settings.TEST` first and hardcodes `db:5432`.
Change priority: if `CLICKHOUSE_HOGQL_RDSPROXY_*` env vars are set, use them regardless of DEBUG mode.

```python
def build_function_call(postgres_table_name, context=None):
    # ... (param helper unchanged)

    table = add_param(postgres_table_name)

    # Prefer explicit RDSPROXY config when available (production + eval environments).
    # This check must come FIRST because:
    # 1. In production: RDSPROXY vars are always set
    # 2. In online eval: RDSPROXY vars point to Aurora, even though DEBUG=1 or
    #    TEST=True (TEST is auto-detected from pytest in sys.argv)
    # 3. In local dev: RDSPROXY vars are NOT set → falls through to DEBUG path
    host_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST
    if host_var:
        port_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT
        database_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE
        user_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_USER
        password_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD

        if not port_var or not database_var or not user_var or not password_var:
            raise ValueError("CLICKHOUSE_HOGQL_RDSPROXY env vars partially configured")

        address = add_param(f"{host_var}:{port_var}")
        db = add_param(database_var)
        user = add_param(user_var)
        password = add_param(password_var)
    elif settings.DEBUG or settings.TEST:
        # Local Docker Postgres (dev/test only, no RDSPROXY configured)
        databases = settings.DATABASES
        model_name = postgres_table_name.replace("posthog_", "")
        db_name = "persons_db_writer" if model_name in PERSONS_DB_MODELS else "default"
        database = databases[db_name]
        address = add_param("db:5432")
        db = add_param(database["NAME"])
        user = add_param(database["USER"])
        password = add_param(database["PASSWORD"])
    else:
        raise ValueError("CLICKHOUSE_HOGQL_RDSPROXY env vars missing")

    return f"postgresql({address}, {db}, {table}, {user}, {password})"
```

This change is backwards-compatible:

- **Production**: RDSPROXY vars set → uses them (same as before, same code path)
- **Local dev** (DEBUG=1, no RDSPROXY): falls back to Docker postgres (same as before)
- **Eval container** (RDSPROXY set to Aurora): uses Aurora even though DEBUG=1 / pytest sets TEST=True
- **Unit tests** (TEST=True, no RDSPROXY): falls back to Docker postgres (same as before)

### Step 2: Aurora database lifecycle manager

**New file**: `ee/hogai/eval/offline/aurora_manager.py`

Manages per-eval-run databases on the shared Aurora instance.

```python
class AuroraEvalDatabaseManager:
    """Creates and destroys per-eval-run databases on the Aurora instance."""

    def __init__(self, aurora_host, aurora_port, aurora_admin_user, aurora_admin_password, aurora_admin_database):
        # Store connection details for admin operations

    def create_eval_database(self, run_id: str) -> str:
        """Create a new database named eval_run_{run_id}. Returns the database name."""
        # Connect to Aurora admin database
        # CREATE DATABASE eval_run_{run_id}
        # Return database name

    def run_migrations(self, database_name: str):
        """Run Django migrations against the eval database."""
        # Use Django's call_command('migrate', database=...) or direct SQL

    def cleanup_eval_database(self, run_id: str):
        """Drop the eval database after the run completes."""
        # DROP DATABASE IF EXISTS eval_run_{run_id}
```

### Step 3: Modify snapshot loader to work with Aurora

**File**: `ee/hogai/eval/offline/snapshot_loader.py`

The existing `SnapshotLoader` already loads into Django ORM via `settings.DATABASES`.
Minimal changes needed — the Django `DATABASES` setting just needs to point to Aurora.

Add Aurora database creation/cleanup as a context manager:

```python
class SnapshotLoader:
    def __init__(self, context, config, aurora_manager=None):
        self.aurora_manager = aurora_manager
        # ... existing init

    async def load_snapshots(self):
        # If aurora_manager provided, create eval database first
        if self.aurora_manager:
            self.eval_db_name = self.aurora_manager.create_eval_database(self.config.experiment_id)
            self.aurora_manager.run_migrations(self.eval_db_name)
            # Update DATABASES setting to point to this database
            # Update CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE

        # ... rest of existing load_snapshots (unchanged — uses Django ORM)
```

### Step 4: New Docker entrypoint for agent evals

**New file**: `bin/docker-agent-evals`

Unlike `bin/docker-ai-evals`, this does NOT start local CH/Postgres services.

```bash
#!/bin/bash
set -e
export DEBUG=1
export IN_EVAL_TESTING=1
export EVAL_MODE=online
export EXPORT_EVAL_RESULTS=1

# Env vars set by Dagster:
# CLICKHOUSE_HOST, CLICKHOUSE_SECURE, etc. → production CH
# CLICKHOUSE_HOGQL_RDSPROXY_READ_* → Aurora (overrides DEBUG path in build_function_call)
# PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE → Aurora (for Django ORM)

cleanup() {
    # Eval database cleanup handled by Dagster after container exits
    echo "Agent eval container shutting down..."
}
trap cleanup EXIT INT TERM

# Run Django migrations against Aurora eval database
# This creates all tables (snapshotted ones get populated, others remain empty)
python manage.py migrate --run-syncdb

# Run the agent evaluation
if [ -z "$EVAL_SCRIPT" ]; then
    echo "Error: EVAL_SCRIPT environment variable is not set"
    exit 1
fi
$EVAL_SCRIPT
```

Note: The entrypoint no longer starts local Docker services (no `docker compose up`).
Django migrations create all Postgres tables on Aurora — only the 4 snapshotted models
(team, property_definitions, group_type_mappings, data_warehouse_tables) will have data;
other system tables (cohorts, dashboards, etc.) will exist but be empty.

### Step 5: New Dockerfile for agent evals

**New file**: `Dockerfile.agent-evals`

Similar to `Dockerfile.ai-evals` but:

- No Docker-in-Docker (no local CH/Postgres needed)
- Includes Node.js for `mcp-remote`
- Includes Agents SDK dependencies

```dockerfile
FROM python:3.12.12-slim-bookworm AS python-base
FROM ghcr.io/astral-sh/uv:0.10.2 AS uv
FROM python-base

# Install system deps + Node.js (for mcp-remote)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git libpq-dev libxmlsec1 libxmlsec1-dev libffi-dev \
    zlib1g-dev pkg-config curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g mcp-remote \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
WORKDIR /code

# Install Python deps
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/python-runtime
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-binary-package lxml --no-binary-package xmlsec

# Copy project files
COPY bin/ ./bin/
COPY manage.py manage.py
COPY common/ common/
COPY posthog posthog/
COPY products/ products/
COPY ee ee/

ENV PATH=/python-runtime/bin:$PATH PYTHONPATH=/python-runtime
RUN chmod +x bin/*

CMD bin/docker-agent-evals
```

### Step 6: Dagster pipeline for agent evals

**New file**: `products/posthog_ai/dags/run_agent_evaluation.py`

Orchestrates the full flow:

1. Prepare dataset
2. Create Aurora eval database
3. Snapshot Postgres data + load into Aurora
4. Spawn agent eval container with production CH + Aurora credentials
5. Cleanup Aurora database

Key differences from existing `run_evaluation.py`:

- Adds Aurora database lifecycle management
- Passes production CH credentials instead of relying on local CH
- Uses `Dockerfile.agent-evals` image
- No need for ClickHouse taxonomy snapshots (agent queries CH directly)

```python
@dagster.op
def create_aurora_eval_database(context, config):
    """Create a per-run database on Aurora and run migrations."""
    manager = AuroraEvalDatabaseManager(...)
    db_name = manager.create_eval_database(context.run_id)
    manager.run_migrations(db_name)
    return db_name

@dagster.op
def load_snapshots_to_aurora(context, eval_db_name, postgres_snapshots):
    """Load Avro snapshots from S3 into the Aurora eval database."""
    # Use SnapshotLoader with Aurora-backed DATABASES

@dagster.op
def spawn_agent_eval_container(context, config, docker_pipes_client, ...):
    """Spawn Docker container with production CH + Aurora credentials."""
    env = {
        # Production ClickHouse (read-only)
        "CLICKHOUSE_HOST": settings.CLICKHOUSE_HOST,
        "CLICKHOUSE_SECURE": "true",
        "CLICKHOUSE_USER": settings.EVAL_CH_READONLY_USER,
        "CLICKHOUSE_PASSWORD": settings.EVAL_CH_READONLY_PASSWORD,
        # Aurora for system tables
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST": settings.EVAL_AURORA_HOST,
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT": settings.EVAL_AURORA_PORT,
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE": eval_db_name,
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_USER": settings.EVAL_AURORA_USER,
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD": settings.EVAL_AURORA_PASSWORD,
        # Django ORM → same Aurora database
        "DATABASE_URL": f"postgres://{user}:{password}@{host}:{port}/{eval_db_name}",
        # MCP + Agent config
        "ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY,
        ...
    }

@dagster.op
def cleanup_aurora_eval_database(context, eval_db_name):
    """Drop the eval database after the run completes."""
    manager = AuroraEvalDatabaseManager(...)
    manager.cleanup_eval_database(eval_db_name)

@dagster.job
def run_agent_evaluation():
    prepared_dataset = prepare_dataset()
    team_ids = prepare_evaluation(prepared_dataset)
    postgres_snapshots = team_ids.map(snapshot_postgres_team_data)
    eval_db_name = create_aurora_eval_database()
    load_snapshots_to_aurora(eval_db_name, postgres_snapshots.collect())
    spawn_agent_eval_container(prepared_dataset, eval_db_name)
    cleanup_aurora_eval_database(eval_db_name)
```

### Step 7: MCP server configuration in eval container

The agent needs MCP tools. Two approaches (recommend approach A):

**Approach A: Stdio MCP server wrapping Django tools (recommended)**

- Create a lightweight Python MCP server (`ee/hogai/eval/online/mcp_stdio_server.py`)
  that wraps `MCPToolRegistry` tools and serves them via stdio transport
- No Django web server needed — tools are invoked directly in-process
- Agents SDK launches this as a subprocess MCP server
- Uses the `mcp` Python package (already available or easily added)

```python
# ee/hogai/eval/online/mcp_stdio_server.py
class EvalMCPServer:
    """Wraps Django MCP tools as a stdio MCP server for the eval agent."""
    def __init__(self, team: Team, user: User):
        self.server = Server("posthog-eval")
        for tool_name in mcp_tool_registry.get_names():
            self._register_tool(tool_name, team, user)
    # Agent SDK config: {"command": "python", "args": ["ee/hogai/eval/online/mcp_stdio_server.py", ...]}
```

**Approach B: Django API + mcp-remote**

- Django dev server runs in the container exposing `MCPToolsViewSet`
- `mcp-remote` connects to this local Django server
- More moving parts, but reuses existing REST API infrastructure

### Step 8: Settings additions

**File**: `posthog/settings/data_warehouse.py`

Add eval-specific Aurora settings:

```python
EVAL_AURORA_HOST: str | None = os.getenv("EVAL_AURORA_HOST")
EVAL_AURORA_PORT: str | None = os.getenv("EVAL_AURORA_PORT", "5432")
EVAL_AURORA_ADMIN_USER: str | None = os.getenv("EVAL_AURORA_ADMIN_USER")
EVAL_AURORA_ADMIN_PASSWORD: str | None = os.getenv("EVAL_AURORA_ADMIN_PASSWORD")
EVAL_AURORA_ADMIN_DATABASE: str | None = os.getenv("EVAL_AURORA_ADMIN_DATABASE", "postgres")
```

## Key Files to Modify

| File                                       | Change                                       |
| ------------------------------------------ | -------------------------------------------- |
| `posthog/hogql/database/postgres_table.py` | Prefer RDSPROXY env vars over DEBUG fallback |
| `posthog/settings/data_warehouse.py`       | Add eval Aurora settings                     |
| `ee/hogai/eval/offline/snapshot_loader.py` | Support Aurora database manager              |

## New Files to Create

| File                                               | Purpose                                                      |
| -------------------------------------------------- | ------------------------------------------------------------ |
| `ee/hogai/eval/online/__init__.py`                 | Package init                                                 |
| `ee/hogai/eval/online/aurora_manager.py`           | Aurora eval database lifecycle (create/migrate/cleanup)      |
| `ee/hogai/eval/online/snapshot_loader.py`          | Loads S3 Avro snapshots into Aurora (reuses existing schema) |
| `ee/hogai/eval/online/mcp_stdio_server.py`         | Stdio MCP server wrapping Django MCP tools                   |
| `ee/hogai/eval/online/agent_runner.py`             | Claude Code SDK agent runner                                 |
| `ee/hogai/eval/online/conftest.py`                 | Pytest fixtures for online eval mode                         |
| `bin/docker-agent-evals`                           | Entrypoint for agent eval containers (no local services)     |
| `Dockerfile.agent-evals`                           | Docker image for agent evals (no DinD)                       |
| `products/posthog_ai/dags/run_agent_evaluation.py` | Dagster pipeline for agent evals                             |

## Infrastructure Prerequisites

1. **Aurora instance** accessible from both:
   - The eval Docker container (for Django ORM operations)
   - The production ClickHouse cluster (for `postgresql()` function calls)
2. **Read-only ClickHouse credentials** for the eval agent (consider a dedicated `EVAL` user context)
3. **Network connectivity**: Production CH VPC must have access to the Aurora instance
4. **S3 access**: Eval container needs access to snapshot bucket

## Verification

1. **Unit test** for `build_function_call()` change:
   - Test: RDSPROXY vars set + DEBUG=True → uses RDSPROXY (new behavior)
   - Test: RDSPROXY vars unset + DEBUG=True → uses DATABASES (existing behavior)
   - Test: RDSPROXY vars set + DEBUG=False → uses RDSPROXY (existing behavior)

2. **Integration test**: Aurora database lifecycle
   - Create database → run migrations → load snapshot → verify tables → cleanup

3. **End-to-end test**: Run a HogQL query through the eval container
   - `SELECT count() FROM events WHERE team_id = X` → production CH
   - `SELECT * FROM system.cohorts WHERE team_id = X` → Aurora via CH `postgresql()`

4. **Agent smoke test**: Run Agents SDK with MCP tools against the eval environment
   - Agent calls `read_data_warehouse_schema` → returns schema
   - Agent calls `execute_sql` with system table query → returns Aurora data
   - Agent calls `execute_sql` with events query → returns production CH data
