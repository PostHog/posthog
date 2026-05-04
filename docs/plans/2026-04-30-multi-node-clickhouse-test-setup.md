# Multi-Node ClickHouse Test Setup (Migration Smoke Tests)

## Context

Today every test environment (local dev, `ci-backend.yml`, `clickhouse-udfs.yml`)
runs a **single ClickHouse container** even though production runs five logical
clusters: the primary `posthog` cluster plus four satellites — `ai_events`,
`aux`, `ops`, `sessions`. The single-node setup masks a class of bugs:

- Migrations that target `NodeRole.AI_EVENTS` / `AUX` / `OPS` / `SESSIONS` are
  silently coerced to `NodeRole.ALL` in `posthog/clickhouse/client/migration_tools.py:78`
  whenever `DEBUG=true` or `TEST=true`, so a migration that forgets to declare
  `node_roles=...` (or declares the wrong role) would still pass CI.
- `Distributed(...cluster=CLICKHOUSE_AI_EVENTS_CLUSTER)` style table definitions
  (e.g. `posthog/models/ai_events/sql.py:194`) are only exercised against a
  cluster that has one and only one host, hiding cross-node connectivity issues.
- Satellite cluster discovery via `cluster.__get_satellite_cluster_hosts()`
  (queries `clusterAllReplicas(<satellite>, system.clusters)` and matches
  `getMacro('hostClusterRole')`) never has a real choice to make.

We want an **opt-in** alternative environment that boots one ClickHouse server
per logical cluster, runs all ClickHouse migrations end-to-end against it, and
verifies every node ends up with the tables it should have. We are explicitly
**not** running the full Python test suite against this stack — the goal is a
focused migration smoke test that catches "wrong cluster / wrong role" bugs
before they reach prod.

The current single-node setup remains the default for `bin/start`, dev work,
and the existing `ci-backend.yml` test job — nothing about that pipeline
changes. The new setup is reachable through a new compose file, a new bin
script, a new `hogli` task, and a new GitHub Actions workflow.

## Topology

Five ClickHouse containers + the existing zookeeper. All on the same docker
network so they can reach each other by service name. Single replica per
cluster (no sharding/replication exercise — out of scope for smoke tests).

| Service name           | hostClusterRole | Belongs to logical cluster | tcp_port |
| ---------------------- | --------------- | -------------------------- | -------- |
| `clickhouse-data`      | `data`          | `posthog`, `posthog_*`     | 9000     |
| `clickhouse-ai-events` | `ai_events`     | `ai_events`                | 9000     |
| `clickhouse-aux`       | `aux`           | `aux`                      | 9000     |
| `clickhouse-ops`       | `ops`           | `ops`                      | 9000     |
| `clickhouse-sessions`  | `sessions`      | `sessions`                 | 9000     |

`posthog_migrations` lists **all five** hosts as separate shards so
`cluster.map_hosts_by_roles()` can fan migrations out to the right node based
on the `hostClusterRole` macro — this is the same trick already used for
`coordinator` in `docker/clickhouse/config.d/coordinator.xml`, just generalised.

## Files to add

### 1. Per-node ClickHouse XML configs

Add five files under `docker/clickhouse/config.d/multinode/` mirroring the
existing `data_node.xml` / `coordinator.xml` pattern:

- `data_node.xml` — `<hostClusterRole>data</hostClusterRole>`, `<shard>01</shard>`
- `ai_events_node.xml` — `<hostClusterRole>ai_events</hostClusterRole>`
- `aux_node.xml` — `<hostClusterRole>aux</hostClusterRole>`
- `ops_node.xml` — `<hostClusterRole>ops</hostClusterRole>`
- `sessions_node.xml` — `<hostClusterRole>sessions</hostClusterRole>`

Each file declares the **same** `<remote_servers>` block (so every node has the
identical view of cluster topology) — only the `<macros>` block differs. The
`<remote_servers>` block contains:

- `posthog`, `posthog_single_shard`, `posthog_writable`, `posthog_primary_replica`
  → single shard pointing at `clickhouse-data:9000`
- `posthog_migrations` → five shards, one per service
  (`clickhouse-data`, `clickhouse-ai-events`, `clickhouse-aux`,
  `clickhouse-ops`, `clickhouse-sessions`), each on port 9000
- `ai_events` → single shard, single replica → `clickhouse-ai-events:9000`
- `aux` → `clickhouse-aux:9000`
- `ops` → `clickhouse-ops:9000`
- `sessions` → `clickhouse-sessions:9000`

This is 5 short XML files; we can introduce a small Python generator
(`bin/generate-multinode-clickhouse-configs.py`) that emits all five from a
single template if duplication becomes painful, but a static set is fine to
start.

### 2. Docker compose stack

New file: `docker-compose.multinode-clickhouse.yml`. Reuses
`docker-compose.base.yml` for `zookeeper` only (and `kafka`/`objectstorage` if
any migration needs them — most dwon't, double-check during implementation).
Defines five `clickhouse-*` services that:

- Pull `clickhouse/clickhouse-server:26.3.9.8` (same image as `docker-compose.base.yml`).
- Mount their respective `docker/clickhouse/config.d/multinode/<role>_node.xml`
  into `/etc/clickhouse-server/config.d/default.xml` (overriding the single-node
  one).
- Mount the existing `docker/clickhouse/config.xml`,
  `docker/clickhouse/users-dev.xml` (or `users.xml`) and `dev-memory.xml`.
- Mount the same `user_defined_function.xml` (UDFs) so migrations that depend
  on UDFs don't break — referenced from `docker/clickhouse/user_defined_function.xml`.
- Each declares a `healthcheck` running `clickhouse-client --query 'SELECT 1'`.
- All depend on `zookeeper` being healthy.

### 3. Bin script for local dev

New file: `bin/start-multinode-clickhouse`. Thin wrapper around:

```bash
docker compose \
  -f docker-compose.base.yml \
  -f docker-compose.multinode-clickhouse.yml \
  up -d clickhouse-data clickhouse-ai-events clickhouse-aux clickhouse-ops clickhouse-sessions zookeeper
```

with a follow-up `docker compose ... ps` and a hint to set
`CLICKHOUSE_HOST=clickhouse-data` (or `localhost` with the published port) before
running migrations.

### 4. Bin script for smoke test

New file: `bin/multinode-migration-smoke`. End-to-end runner that:

1. Boots the multinode compose stack and waits for all five containers to pass
   their healthcheck (`bin/ci-wait-for-docker` already exists — reuse it).
2. Exports env vars so `manage.py migrate_clickhouse` connects to the data
   node:
   - `CLICKHOUSE_HOST=clickhouse-data` (or `localhost` with mapped port for local)
   - `CLICKHOUSE_CLUSTER=posthog`
   - `CLICKHOUSE_MIGRATIONS_CLUSTER=posthog_migrations`
   - `CLICKHOUSE_SATELLITE_CLUSTERS=ai_events,aux,ops,sessions`
   - `MULTINODE_CLICKHOUSE=1` (new — see §6)
3. Runs `python manage.py migrate_clickhouse`.
4. Runs the verification step (see §5).
5. On failure, dumps logs from each container and `system.errors` from each.
6. On success, tears the stack down (or leaves it up if `KEEP=1`).

### 5. Verification step

New file: `posthog/clickhouse/test/test_multinode_smoke.py` (or a standalone
`scripts/verify_multinode_clickhouse.py` to keep it out of the pytest default
collection). Connects to **each of the five nodes individually** via the
`clickhouse-driver` Client, and asserts:

- **Per-cluster table presence** — for each satellite role, query
  `system.tables WHERE database = 'posthog'` on the corresponding node and
  diff against an expected manifest. Expected manifest is generated from
  existing `sql.py` modules and migration metadata: any table whose
  `Distributed(...)` clause references `CLICKHOUSE_AI_EVENTS_CLUSTER` (or
  `_AUX`, `_OPS`, `_SESSIONS`) must be reachable from the matching node.
- **No leakage** — tables that are not declared on a satellite cluster must
  not be present on that node's local schema (catches migrations that forgot
  `node_roles=` and accidentally created a table everywhere).
- **`system.clusters` view** — each node's `system.clusters` must list the
  expected hosts for every cluster (sanity check that the XML mounted
  correctly).
- **`getMacro('hostClusterRole')`** — assert each node returns its expected
  role, so the discovery logic in `posthog/clickhouse/cluster.py` lines
  161–178 has real values to match against.

The expected manifest lives next to the test as a YAML/Python dict so adding a
new table-on-cluster is a one-line PR.

### 6. Disable the `NodeRole.ALL` override under multinode

Edit `posthog/clickhouse/client/migration_tools.py` so the existing block at
line 78 (which collapses node roles to `ALL` when `DEBUG=true` or `TEST=true`)
respects an opt-out:

```python
if (settings.DEBUG or settings.TEST) and not settings.MULTINODE_CLICKHOUSE:
    node_roles_list = [NodeRole.ALL]
```

Add `MULTINODE_CLICKHOUSE` (default `False`) to
`posthog/settings/data_stores.py` near the other `CLICKHOUSE_*` settings.

This is the single behaviour change to existing code — everything else is
additive. The default path (no env var set) stays exactly as it is today.

### 7. Hogli command

Add a `hogli` task that wraps `bin/multinode-migration-smoke`. The hogli
config is in `bin/hogli` / `package.json` turbo pipeline — exact location
discovered during implementation. Expose as `hogli test:multinode-migrations`.

### 8. GitHub Actions workflow

New file: `.github/workflows/ci-clickhouse-multinode-migrations.yml`. Triggers
on `pull_request` and `merge_group`, paths-filtered to:

```yaml
- 'posthog/clickhouse/migrations/**'
- 'posthog/models/**/sql.py'
- 'posthog/settings/data_stores.py'
- 'posthog/clickhouse/cluster.py'
- 'posthog/clickhouse/client/migration_tools.py'
- 'docker/clickhouse/config.d/multinode/**'
- 'docker-compose.multinode-clickhouse.yml'
- 'bin/multinode-migration-smoke'
- 'posthog/clickhouse/test/test_multinode_smoke.py'
```

Single job, `timeout-minutes: 20`, that:

1. Checks out, sets up Python (uv), installs the minimal deps needed by
   `manage.py migrate_clickhouse`.
2. Runs `bin/multinode-migration-smoke`.
3. On failure, uploads `docker compose logs` as an artifact.

## Critical files (existing) referenced

- `posthog/clickhouse/client/migration_tools.py` (line 78) — `NodeRole.ALL` override; the only existing file we modify.
- `posthog/clickhouse/cluster.py` (lines 98–178, 499–523) — `ClickhouseCluster.__get_satellite_cluster_hosts()` is what we're trying to actually exercise.
- `posthog/clickhouse/client/connection.py` (lines 23–40) — `NodeRole` enum, including `AI_EVENTS`, `AUX`, `OPS`, `SESSIONS`.
- `posthog/settings/data_stores.py` (lines 278–291) — settings constants; we add `MULTINODE_CLICKHOUSE` here.
- `posthog/management/commands/migrate_clickhouse.py` — migration entry point; no change needed.
- `docker/clickhouse/config.d/default.xml` (single-node, unchanged), `data_node.xml` and `coordinator.xml` (precedent we're imitating).
- `docker-compose.base.yml` (line for `clickhouse:` service — we leave this alone; the new compose file is a sibling).
- `bin/ci-wait-for-docker` — reused by the smoke runner.
- `posthog/models/ai_events/sql.py:194` — example of `Distributed(...cluster=CLICKHOUSE_AI_EVENTS_CLUSTER)` to seed the verification manifest.

## Build sequence

1. Add `MULTINODE_CLICKHOUSE` setting + the two-line edit in
   `migration_tools.py`. Verify existing single-node CI still green
   (`MULTINODE_CLICKHOUSE` defaults to false → no behaviour change).
2. Add the five XML configs under `docker/clickhouse/config.d/multinode/`.
3. Add `docker-compose.multinode-clickhouse.yml`. Verify locally with
   `docker compose ... up`, then run `clickhouse-client --query "SELECT * FROM system.clusters"`
   against each node to confirm cluster topology is what we expect.
4. Add `bin/start-multinode-clickhouse` for ergonomics.
5. Add `bin/multinode-migration-smoke` and run it locally — first iteration
   probably surfaces a few migrations with missing `node_roles=` declarations;
   fix or document those before continuing.
6. Add `posthog/clickhouse/test/test_multinode_smoke.py` (or the standalone
   verification script) with the expected manifest.
7. Wire up the hogli task.
8. Add the GitHub Actions workflow last, once the local pipeline is reliable.

## Verification

End-to-end check, run from a clean worktree:

```bash
bin/multinode-migration-smoke
```

Should:

- bring up five ClickHouse containers
- successfully run `manage.py migrate_clickhouse` against the data node
- pass the verification step (per-node table presence, no leakage, macro check)
- print a summary like `5 nodes, 187 migrations applied, 0 unexpected tables`

Manual inspection during implementation:

```bash
# pick any container and confirm cluster topology is identical across nodes
docker compose -f docker-compose.multinode-clickhouse.yml exec clickhouse-aux \
  clickhouse-client --query "SELECT cluster, host_name, port FROM system.clusters ORDER BY cluster, shard_num"

# confirm the macros differ per node
for svc in clickhouse-data clickhouse-ai-events clickhouse-aux clickhouse-ops clickhouse-sessions; do
  docker compose -f docker-compose.multinode-clickhouse.yml exec "$svc" \
    clickhouse-client --query "SELECT '$svc' AS node, getMacro('hostClusterRole') AS role"
done

# confirm an ai_events table only exists on the ai_events node
docker compose -f docker-compose.multinode-clickhouse.yml exec clickhouse-ai-events \
  clickhouse-client --query "SHOW TABLES FROM posthog LIKE '%ai_event%'"
docker compose -f docker-compose.multinode-clickhouse.yml exec clickhouse-aux \
  clickhouse-client --query "SHOW TABLES FROM posthog LIKE '%ai_event%'"  # should be empty
```

CI verification: open a draft PR that intentionally mis-targets a migration
(e.g. drops the `node_roles=[NodeRole.AI_EVENTS]` from a recent ai_events
migration). The new workflow should fail; the existing `ci-backend.yml` will
still pass — confirming the new check catches a real bug class that today's
pipeline misses.

## Out of scope

- Replication / multi-shard topology. Single replica per cluster only.
- Running the full Python test suite against the multinode stack — addressable
  later if migration smoke tests reveal demand.
- Touching `bin/start` or any default-dev workflow.
- Production cluster XML (`docker/clickhouse/config.d/default.xml`,
  `data_node.xml`, `coordinator.xml`) — left alone.
