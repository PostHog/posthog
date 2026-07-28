# Query schema migrations

Versioned migrations for the JSON query schema (`TrendsQuery`, `RetentionQuery`, ...), analogous to Django migrations but for query nodes stored as JSON: in insights, endpoints, cohorts, notebooks, URLs, and templates.

## How it works

- Every query node has an optional `version` field. **A missing or `null` version means version 1.**
- A migration file (`NNNN_description.py`) declares `targets = {"<NodeKind>": <version>}` and a `transform(query: dict) -> dict` that converts a node from that version to the next. The version bump happens in the base class, not in `transform`.
- `upgrade(query)` (`upgrade.py`) walks a query dict recursively (any nesting: `InsightVizNode.source`, series arrays, ...) and replays migrations on every node whose `version` is below `LATEST_VERSIONS[kind]`.
- `upgrade_query(insight)` (`upgrade_manager.py`) additionally converts legacy filters-based insights to query-based ones first. Note: it mutates `insight.query` in memory and does not restore it on exit.
- Discovery (`__init__.py`) is lazy and validated: duplicate `(kind, version)` targets raise, and `validate.py` (exercised in CI by `test_validate.py::test_linear`) rejects gaps and non-linear versions.

## Where upgrades happen

Read/execute-time (always-on):

- `/api/.../query` and `process_query_dict` upgrade before pydantic validation.
- `POST /api/environments/:id/query/upgrade` is called by the frontend for untrusted queries (URL-embedded, notebook nodes).
- Insight serializers upgrade on read; caching, alerts, exports, and subscriptions go through `upgrade_query`.
- Endpoints upgrade their immutable `EndpointVersion.query` snapshots at execution/materialization time; cohorts upgrade their saved `query` when compiling.

Write-time (backfill): a Temporal schedule (`upgrade-queries-schedule`, every 6 hours, see `posthog/temporal/product_analytics/`) rewrites stored **insights** whose queries are below the latest versions. Other stores (endpoint snapshots, notebook content, dashboard templates, cohort queries) are _not_ rewritten and rely on read-time upgrades forever.

## Adding a migration

1. Create `NNNN_description.py` (next free number, must match `^\d{4}[a-zA-Z_]*\.py$`) with a `Migration(SchemaMigration)` class. Target the _current_ latest version of each kind (see `LATEST_VERSIONS` or `frontend/src/queries/latest-versions.json`).
2. Add a test in `test/` covering the transform, including the no-op cases below.
3. Regenerate the frontend versions file: `python bin/build-schema-latest-versions.py` (part of `hogli build:schema` / `pnpm run schema:build`) and commit `frontend/src/queries/latest-versions.json` **in the same PR**, otherwise `test_discovery.py::test_frontend_latest_versions_file_in_sync` fails. A stale file makes the frontend stamp outdated versions on new queries, which double-applies your migration to already-new-shape queries.
4. Keep the schema backward compatible: leave the old field in `frontend/src/queries/schema/*.ts` (and thus `posthog/schema.py`) until the backfill has completed and no writer emits it anymore. Removing it immediately breaks validation of not-yet-upgraded JSON everywhere.

## Invariants for `transform`

- **Must be a safe no-op on queries already in the new shape.** All unversioned queries are treated as version 1, and plenty of new-shape queries are created without a version stamp (`filter_to_query` conversions, dashboard templates, hand-written API payloads). Guard on the presence of the old field, like the existing migrations do.
- **Must tolerate missing/None fields.** Stored JSON is not validated before `transform` runs; a `KeyError` here fails query processing for that insight (and marks it failed in the backfill workflow).
- **Must not change `kind`**: the version bump reads `targets[query["kind"]]` after the transform.
- Two migrations must not target the same `(kind, version)`: discovery raises. If you race another PR, rebase and bump your target version.
