# Managed warehouse connections in the SQL editor

The `managed-warehouse-sql-editor` feature flag switches which managed warehouse connection appears for each project:

- When disabled, which is the default, PostHog keeps the source as an ordinary external Duckgres connection. External-source access controls apply, the option uses DuckDB branding and source settings, and queries use the existing PostgreSQL direct adapter.
- When enabled, PostHog hides the external representation from the connection chooser. If the reserved source contains a configured Duckgres `project_reader` credential, it appears as `PostHog (Managed warehouse)` below `PostHog (ClickHouse)`. Every project member can use it without external-source access controls.

Enabling the flag without a ready project reader shows neither representation. The flag only controls chooser visibility. It does not change a source row's adapter or access policy, revoke saved connection IDs, or create, rotate, or delete credentials or catalog metadata.

Duckgres enforces the reader's read-only, project-scoped query policy in built-in mode. PostHog requires the reserved source to be enabled, marked as a configured `project_reader`, and use the expected `posthog_team_<team_id>` login. Sources backed by the organization login and pending or malformed readers are not eligible for built-in mode. This integration assumes provisioning has already created the project reader.

A ready project-reader source always uses the built-in policy, even while hidden. Raw queries use a native pgwire adapter. The adapter uses the exact reader connection stored on the resolved source, sends one SQL statement unchanged, and does not build a HogQL database or load the third-party PostgreSQL source stack. It never falls back to the organization's stored login. Duckgres authorizes `project_reader` statements through its PostgreSQL query gateway, so raw statements must use PostgreSQL-compatible syntax. Queries that return more than 50,000 rows fail and ask the user to add a `LIMIT` clause. Non-raw queries continue through the PostgreSQL and HogQL path with the same source credential.

Hostname resolution is bounded to 15 seconds before libpq applies its per-attempt 15-second connection timeout. Canceling an asynchronous query signals the active pgwire connection instead of only revoking its Celery task.

A legacy source backed by the stored server login always remains an external connection, even while hidden from the chooser. It stays visible in external-source management, keeps external-source and table access controls, and uses the existing PostgreSQL direct adapter.

PostHog reconciles the legacy connection and a ready reader into separate table catalogs. A failure or missing credential in one mode does not block the other. Reconciliation runs when warehouse status is read, coalesced to once a minute, and in a twice-hourly periodic sweep. Duckgres limits reader discovery to the project's allowed namespaces. The sweep makes newly created tables visible without requiring a visit to Data ops. Each source reconcile opens a warehouse session, so it is not more frequent. If a physical table is dropped and recreated with the same name, reconciliation revives its existing catalog entry.

The configured source row is the local readiness marker for built-in mode. Query and picker paths use its encrypted reader connection directly. If the reader no longer exists in Duckgres, connection attempts fail without trying a broader credential.

Deploy this code to every web and Celery worker before provisioning project-reader rows. Older workers can mistake the newest reserved row for the legacy source and replace its credentials. Keep the feature flag disabled until a ready reader exists for the project.
