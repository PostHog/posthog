# Managed warehouse connections in the SQL editor

Provisioning a managed warehouse creates a system-owned direct connection for each participating project. The connection uses a distinct Duckgres project-reader login and appears in the SQL editor's database chooser.

The project reader can query the project's event and person tables and every current or future table in its team, data-import, and modeled-data schemas. The exposed namespaces mirror the Duckgres org-team row (which credential setup never rewrites), so hand-set layouts such as legacy `posthog.events` tables stay in sync. Duckgres enforces the read-only project boundary for both PostgreSQL and Flight SQL queries.

PostHog reconciles the connection's table catalog when the warehouse status is read (coalesced to once a minute) and in a twice-hourly periodic sweep. The sweep makes newly created tables visible without requiring a visit to Data ops; each reconcile opens a real warehouse session, which is why it is not more frequent. If a physical table is dropped and recreated with the same name, reconciliation revives its existing catalog entry.

## Published modeled tables

The feature flag `data-ops-published-tables` adds a **Published tables** tab to Data ops for projects with a ready managed warehouse. Editors can publish a modeled Duckgres table as a snapshot in PostHog, monitor its status, publish it again, or unpublish it. Viewers can inspect publication status and open completed tables in the SQL editor.

Published tables do not refresh automatically. Use **Publish again** after the modeled table changes. Unpublishing removes the PostHog warehouse table and its snapshot without changing the source modeled table.
