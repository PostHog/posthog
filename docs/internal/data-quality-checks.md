# Data quality checks

Data quality checks audit warehouse tables, saved views, and catalog metrics. Checks keep their identity and history when their assertion changes.

## Authorization

Check and run routes require project membership, query access, and access to the subject. The static check-type catalog does not require query access. Metric checks use catalog permissions. Table and view checks use their respective warehouse object permissions, including explicit object grants and inherited source grants. A resource-wide denial does not discard a more specific grant that the canonical access-control rules permit.

Reading checks, health, and run history requires viewer access. Creating, editing, deleting, or manually running checks requires editor access to their subject. Referenced subjects require viewer access. These checks apply even when the warehouse query-enforcement feature flag is disabled.

Checks and suites are polymorphic: a catalog-only member can read a teammate's metric checks without warehouse access. Project lists filter by each row's subject. A mixed suite is hidden if any recorded run is unreadable, because aggregate counts would otherwise disclose its outcome.

Restricted callers must have access to both the stored and proposed definitions before PUT or PATCH can save anything, including presentation-only edits. Authorization is repeated if a concurrent edit changes the definition accepted by the transaction. An edit makes three attempts. After three attempts it writes nothing and returns HTTP 400 with the code `concurrent_edit`. An unavailable reference fails closed. An authorized caller can still disable a stale check without revalidating its assertion.

A check that reads more than its own subject executes as a user. A manual run executes as the user who started it, and an automated run executes as the user who last wrote the definition. If neither user is available, the run records an error and executes no SQL.

## Token scopes

All routes below also require `query:read`. Write scopes include read access; read-only scopes do not authorize writes. Token scopes limit access independently of the user's grants, including for organization administrators.

| Route                                            | Read scope               | Write scope               |
| ------------------------------------------------ | ------------------------ | ------------------------- |
| Nested warehouse table checks and suite runs     | `warehouse_table:read`   | `warehouse_table:write`   |
| Nested warehouse view checks and suite runs      | `warehouse_view:read`    | `warehouse_view:write`    |
| Nested catalog metric checks and suite runs      | `data_catalog:read`      | `data_catalog:write`      |
| Project-wide checks and runs, warehouse subjects | `warehouse_objects:read` | `warehouse_objects:write` |
| Project-wide checks and runs, metric subjects    | `data_catalog:read`      | `data_catalog:write`      |

A project-wide token may select only the subject types its scopes permit. An unnamed manual sweep skips inaccessible checks; an explicitly selected inaccessible check is rejected. Cross-subject references must also fall within the caller's permitted subject types.

The table above applies to the REST routes only. A raw HogQL query against `system.information_schema.data_quality_*` needs `query:read` and no other scope. The user's own permissions still apply to each row. A token with `query:read` reads metric checks only if its user has catalog access.

## Custom SQL

Custom SQL supports direct relations, subqueries, CTEs, and unions. Metric checks bind `{metric}` before enumerating dependencies. Metric checks cannot use CTEs. Query `{metric}` directly or through a subquery. Expandable table expressions whose dependencies cannot be established, including HogQLX sources and table functions, are rejected during authoring and compilation.

Previously saved definitions that cannot be enumerated remain hidden and unrunnable for restricted callers. Execution permissions do not replace the checks that protect definitions, counts, and history.

## History and discovery

A run is authorized using the subject identities recorded when it executed. Editing a check does not authorize its earlier results. Deleted subjects, unreadable recorded references, and missing dependency records on cross-subject checks remain inaccessible. An authorized edit can return the updated check with historical status fields redacted.

The REST endpoints and `information_schema.data_quality_checks`, `information_schema.data_quality_check_runs`, and `information_schema.data_quality_health` share visibility rules. Their query-cache boundary includes catalog, warehouse, and source permissions.

The overview filters readable subject identities in SQL before scanning definition and history visibility. The remaining scan loads only authorization fields in batches of 200 checks, before counting or paginating. Creator and owner records are hydrated for the returned page. Complex-definition evaluation still scales with the candidate checks; pagination is not constant-cost.

Notification recipient checks retain the existing global warehouse-resource policy. A specific object grant alone does not expand notification delivery eligibility. A subject that no longer resolves sends no notification. Background dependency pinning still resolves references individually; batching that cross-product workflow is separate work.

Catalog access is a project permission resource. Notification visibility follows that permission, including after access is revoked.
