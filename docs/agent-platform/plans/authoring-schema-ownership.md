# Agent platform: one Django-owned product DB

## Decision

Collapse all agent-platform tables — authoring **and** runtime — into a single
dedicated **Django product database** (`agent_platform`). Django owns the schema
and all migrations. The node services (`agent-{ingress,runner,janitor}`) become
pure clients: one connection pool, raw SQL queries, **no** schema management.

Pre-release: **breaking changes are fine, wipe and recreate migrations from
scratch.** No data migration, no `--fake`, no append-only.

This supersedes:

- the node `@posthog/agent-migrations` package (deleted),
- the `agent-migrator` PreSync hook + chart wiring (charts #11869 — reverted;
  the product-DB migration runs via the standard posthog-django migration job),
- the "agent-migrations → runtime-only" cleanup (dropped — replaced by this).

Kept (independent of this): runner `/healthz` server + port lineup (posthog
`ass`), runner probe PR (#11873), janitor Service→80 PR (#11876).

## Target topology

- **DB:** reuse the existing dedicated `agent_platform` Aurora cluster (dev) as
  the product DB, **direct mode** (like `warehouse_sources_queue`).
- **Django:** `products/db_routing.yaml` routes `app_label: agent_platform` →
  `database: agent_platform`. `ProductDBRouter` sends all `agent_platform` ORM
  to it. Migrations run via `migrate_product_databases` (posthog-django job).
- **Node:** one pool at `PRODUCT_DB_AGENT_PLATFORM_*` (authoring + runtime now
  co-located). `PgRevisionStore` + `PgSessionQueue` share it.

## Models (all in products/agent_platform, ProductTeamModel base)

Authoring (exist; convert): `AgentApplication`, `AgentRevision`, skill/tool
templates + revision join tables.
Runtime (new; port the node SQL exactly): `AgentSession`, `AgentUser`,
`AgentSandboxInstance`, `AgentToolApprovalRequest`, `AgentSessionCredential`.

Cross-DB rules (product DB can't FK the main DB):

- `team` FK → `team_id = BigIntegerField(db_index=True)` (via `ProductTeamModel`).
- `created_by` FK → `created_by_id = BigIntegerField(null=True)`.
- Internal FKs **between agent models stay** (same DB): `revision.application`,
  `revision.parent_revision`, `application.live_revision`, session→revision, etc.
- Add `team_id` to every runtime table (node currently keys some off
  `application_id`/`revision_id` only) — required by `ProductTeamModel`, improves
  isolation.

## Phases

### 1. Provision (cloud-infra)

Confirm the `agent_platform` Aurora cluster has a `migrator` user (we have
`agent-migrator`) + the product-DB secret shape
(`postgres-agent-platform-{user}-credentials` with `url`/`url_reader`/...). Wire
`PRODUCT_DB_AGENT_PLATFORM_{WRITER,READER,DIRECT}_URL` to the web app and to the
node services.

### 2. Django models + fresh migration (posthog) — `/django-migrations`

- Convert authoring models to `ProductTeamModel`; FKs→ids per above.
- Add runtime models mirroring the node SQL (`services/agent-migrations/migrations/*.sql`
  is the column/type/index/default reference) — schema parity is critical; the
  node raw SQL must keep working unchanged.
- Delete existing `products/agent_platform/backend/migrations/*`; regenerate a
  single `0001_initial` against the product DB.
- Add the `db_routing.yaml` route.

### 3. DRF / facade rework (posthog) — `/improving-drf-endpoints`

- Authoring viewsets: `TeamAndOrgViewSetMixin` already scopes by `team_id` +
  sets `current_team_id` context (works cross-DB). Fix serializers that traverse
  `obj.team.*` / `obj.created_by.*` → use ids + facade fetch.
- Verify `ModelActivityMixin` works for product-DB models (activity log lives in
  main DB, keyed by `team_id`) — adjust if it assumes same-DB.

### 4. Node services → pure client (posthog)

- Collapse `posthogDb` + `agentDb` to one pool at the product-DB URL in
  `agent-{ingress,runner,janitor}/src/index.ts`.
- Config: replace `POSTHOG_DB_URL` + `AGENT_DB_URL` with one var.
- Delete `services/agent-migrations`; remove all `migrate()`/`reset()` imports.

### 5. Test harness (posthog)

- Harness points at a Django-migrated test product DB (`migrate_product_databases`),
  not `@posthog/agent-migrations`. `reset()` → truncate tables (per-test), not
  drop-schema-and-remigrate.
- Run `pnpm --filter @posthog/agent-tests test` green.

### 6. Charts

- Add `agent_platform` as a `psql:` `productDatabases` entry (dedicated cluster,
  `pgbouncer: false`) in `shared/posthog-django/common.yaml` (+ legacy
  `charts/posthog-django` until retired) so the web app gets the URLs + runs the
  migration.
- Point the node agent apps' DB env at the product DB URL (single).
- Revert the `agent-migrator` PreSync hook (janitor `preSyncHook` + the generic
  `preSyncHook` template if unused elsewhere). Migration now via the Django job.

## Open checks

- Which runtime tables already have `team_id`? (add where missing)
- `ModelActivityMixin` cross-DB behaviour.
- Local dev: `DEBUG=1` auto-connects `posthog_agent_platform` on localhost; align
  `bin/mprocs.yaml` agent-service DB env + the dev DB bootstrap.
