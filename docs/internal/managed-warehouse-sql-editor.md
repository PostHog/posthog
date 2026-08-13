# Managed warehouse connections in the SQL editor

Provisioning a managed warehouse creates a system-owned direct connection for the provisioning project. Onboarding another project creates its connection after the control plane accepts that project. The connection appears as `PostHog (Managed warehouse)` below `PostHog (ClickHouse)` in the SQL editor's database chooser. It is available to every member of that project and is not governed by external-source access controls.

The SQL editor uses the login stored for the organization's Duckgres server. PostHog does not require a particular Duckgres access mode or add a read-only policy. The stored login's permissions determine which statements and relations are available.

Raw queries use a native pgwire adapter. The adapter resolves the current stored login for every request, sends one SQL statement unchanged, and does not build a HogQL database or load the third-party PostgreSQL source stack. Non-raw queries continue through the PostgreSQL and HogQL path.

PostHog reconciles the connection's table catalog when the warehouse status is read (coalesced to once a minute) and in a twice-hourly periodic sweep. The sweep makes newly created tables visible without requiring a visit to Data ops; each reconcile opens a real warehouse session, which is why it is not more frequent. If a physical table is dropped and recreated with the same name, reconciliation revives its existing catalog entry.

The project-scoped connection row is the local enrollment marker. Query and picker paths use that row with the organization's stored server record, so a control-plane outage does not interrupt an already-enrolled project's SQL access. Projects without that marker do not see or resolve the managed warehouse connection.
