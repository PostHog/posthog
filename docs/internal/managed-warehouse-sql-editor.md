# Managed warehouse connections in the SQL editor

The SQL editor recognizes a system-owned managed warehouse connection only after the project's reserved source contains a configured Duckgres `project_reader` credential. The connection appears as `PostHog (Managed warehouse)` below `PostHog (ClickHouse)` in the database chooser. It is available to every member of that project and is not governed by external-source access controls.

Duckgres enforces the reader's read-only, project-scoped query policy. PostHog requires the reserved source to be enabled, marked as a configured `project_reader`, and use the expected `posthog_team_<team_id>` login. Sources backed by the organization login, pending readers, and malformed credentials remain unavailable. This integration does not create or rotate the reader credential.

Raw queries use a native pgwire adapter. The adapter uses the exact reader connection stored on the resolved source, sends one SQL statement unchanged, and does not build a HogQL database or load the third-party PostgreSQL source stack. It never falls back to the organization's stored login. Duckgres authorizes `project_reader` statements through its PostgreSQL query gateway, so raw statements must use PostgreSQL-compatible syntax. Non-raw queries continue through the PostgreSQL and HogQL path with the same source credential.

PostHog reconciles a ready reader connection's table catalog when the warehouse status is read, coalesced to once a minute, and in a twice-hourly periodic sweep. Duckgres limits discovery to the project's allowed namespaces. The sweep makes newly created tables visible without requiring a visit to Data ops. Each reconcile opens a warehouse session, so it is not more frequent. If a physical table is dropped and recreated with the same name, reconciliation revives its existing catalog entry.

The configured source row is the local readiness marker. Query and picker paths use its encrypted reader connection directly. Projects without a ready reader source do not see or resolve the managed warehouse connection. If the reader no longer exists in Duckgres, connection attempts fail without trying a broader credential.
