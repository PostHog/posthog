# Managed warehouse connections in the SQL editor

Provisioning a managed warehouse creates a system-owned direct connection for each participating project. The connection uses a distinct Duckgres project-reader login and appears in the SQL editor's database chooser.

The project reader can query the project's event and person tables and every current or future table in its team, data-import, and modeled-data schemas. Duckgres enforces the read-only project boundary for both PostgreSQL and Flight SQL queries.

PostHog reconciles the connection's table catalog when the warehouse status is read and in a five-minute periodic sweep. The sweep makes newly created tables visible without requiring a visit to Data ops. If a physical table is dropped and recreated with the same name, reconciliation revives its existing catalog entry.
