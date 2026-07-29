# Managed warehouse connections in the SQL editor

Provisioning a managed warehouse creates a system-owned direct connection for each participating project. The connection appears in the SQL editor's database chooser.

## The connection uses the org root credential, not a per-project login

Every participating project's connection authenticates with the organization's Duckgres **root** credential (`credential_kind: "org_root"` in `connection_metadata`, snapshotted into the source's `job_inputs`). Root bypasses Duckgres `AllowedSchemas`, so it sees every schema in the warehouse, and the discover sweep registers the whole org catalog against each project's source.

There is no per-project read boundary in the warehouse today. The only filter on what gets registered is the `INTERNAL_SCHEMAS` denylist in `products/data_warehouse/backend/managed_warehouse_connection.py`, which exists for sidebar hygiene — it drops database engine internals (`pg_catalog`, `information_schema`, `pg_toast`, `system`), not other projects' data. Per-schema visibility control is still a TODO in that module, and it plugs in at the same place.

When answering data-access questions, do not treat this connection as a project-isolation boundary. The `team_id` guard that HogQL injects at print time (`team_id_guard_for_table` in `posthog/hogql/printer/clickhouse.py`) constrains PostHog's own event and person tables; it says nothing about which warehouse schemas a managed connection can read.

## Catalog reconciliation

PostHog reconciles the connection's table catalog when the warehouse status is read (coalesced to once a minute) and in a twice-hourly periodic sweep. The sweep makes newly created tables visible without requiring a visit to Data ops; each reconcile opens a real warehouse session, which is why it is not more frequent. If a physical table is dropped and recreated with the same name, reconciliation revives its existing catalog entry.

## Related

For the separate question of moving event data between two PostHog projects, see [PostHog-to-PostHog event mirroring](./posthog-to-posthog-event-mirroring.md).
