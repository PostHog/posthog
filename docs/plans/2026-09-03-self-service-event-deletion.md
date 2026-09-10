# Self-service event deletion from HogQL

## Context

Customers currently need PostHog staff to translate an event-deletion request into a `DataDeletionRequest` in Django Admin. This creates unnecessary support work and makes customers describe criteria that they can already express precisely in the SQL editor.

The goal is to let an authorized project member write a regular HogQL query, review its result, and submit it as a deletion request. The query must return exactly one column containing event UUIDs. PostHog queues those UUIDs in `adhoc_events_deletion`, and the scheduled `deletes_job` removes the matching events during the weekend deletion window.

The existing backend already provides most of the operational workflow:

- `DataDeletionRequest` records criteria, approval, execution, and verification state.
- Deferred event removals insert `(team_id, uuid)` rows into `adhoc_events_deletion`.
- `deletes_job` builds a dictionary from pending queue rows and deletes matching events from every physical events table.
- The dictionary lookup uses `(team_id, uuid)`, so an event UUID cannot delete an event belonging to a different team.
- A verification job promotes queued deletion requests after `deletes_job` succeeds.

This plan extends that workflow. It does not introduce a second deletion system.

## Requirements

1. An authorized project member can submit the current SQL editor HogQL query as an event-deletion request.
2. The submitted query can use regular HogQL features, including joins, CTEs, subqueries, and unions supported by the normal query path.
3. The query must return exactly one column whose values can be inserted into a ClickHouse `UUID` column.
4. PostHog stores an immutable query and variable snapshot on the deletion request.
5. Requests created through the product are clearly distinguishable from requests created in Django Admin.
6. PostHog executes selection and queue insertion entirely within ClickHouse. Millions of UUIDs must not pass through Python, Postgres, object storage, or a Dagster payload.
7. Customer-controlled text cannot choose the insertion target, queued team ID, provenance, or ClickHouse settings.
8. Queue rows identify the deletion request that created them.
9. Queueing is retry-safe after a timeout or partial distributed failure.
10. The existing weekend `deletes_job` remains the only process that deletes query-selected events.
11. Customers can query their product-created deletion requests through a team-scoped, read-only HogQL table.

## Proposed customer flow

1. The customer writes and runs a HogQL query in the SQL editor.
2. The customer chooses **Delete matching events** from the existing save menu.
3. PostHog validates the current query and calculates a preview count.
4. A confirmation dialog explains that deletion is irreversible and runs during the next deletion window.
5. Submission creates an immutable `DataDeletionRequest` for the current project and user.
6. The existing approval workflow approves the request automatically or routes it for operator review.
7. A Dagster job executes one ClickHouse `INSERT ... SELECT` to queue the selected UUIDs.
8. The request moves to `queued` only after ClickHouse reports that queueing succeeded.
9. The weekend `deletes_job` deletes the queued `(team_id, uuid)` keys.
10. The existing verifier marks the request complete after confirming that the events no longer exist.

The first release should force product-created requests to deferred execution. Customers should not be able to select immediate mutations.

## Store the query on `DataDeletionRequest`

The deletion authority should be an immutable snapshot on `DataDeletionRequest`, not a `DataWarehouseSavedQuery`.

A saved view has independent edit, deletion, and materialization behavior. Referencing it would allow the query to change between review and execution unless the deletion workflow copied it. Storing the snapshot directly provides a smaller and clearer audit boundary.

Add fields equivalent to:

```python
class DataDeletionRequestOrigin(models.TextChoices):
    DJANGO_ADMIN = "django_admin"
    SELF_SERVICE = "self_service"

origin = models.CharField(...)
hogql_query = models.TextField(blank=True, default="")
hogql_variables = models.JSONField(blank=True, default=dict)
```

The exact query representation should match the SQL editor's existing `HogQLQuery` shape. If variable values contain typed query nodes, store the complete serialized variables rather than a flattened value map.

Keep `created_by_staff` as a permanent, independent audit field. It records whether the actor was PostHog staff, while `origin` records which surface created the request. A PostHog employee acting as a customer through the product therefore creates a request with `origin = self_service` and `created_by_staff = true`.

The product creation path derives `created_by_staff` from the authenticated actor and never accepts it from the request body. Existing rows should migrate to `origin = django_admin` only after confirming that Django Admin was their only creation path.

Changing the query or variables must reset the request to draft, clear approval and cached preview data, and invalidate any compiled-query cache. Approved and later requests remain immutable.

## Query validation

The API accepts regular HogQL but never accepts raw ClickHouse SQL.

Validation uses the normal HogQL parser, resolver, access controls, and compiler with the request's project and submitting user. It must establish:

- The input contains one read-only query.
- The resolved output has exactly one column.
- The output is compatible with ClickHouse `UUID`.
- All variables resolve successfully.
- The submitting user can access every referenced HogQL resource.
- The query cannot supply output formatting, an output destination, or execution settings outside the normal HogQL contract.

The query does not need to select syntactically from `events`, and the column does not need to be a direct `events.uuid` AST node. This preserves regular HogQL composition. A customer may derive the final UUID set through joins or unions.

No Python loop needs to validate individual UUID values. ClickHouse query evaluation and insertion into the destination `UUID` column enforce the runtime type. A bad conversion fails the queueing operation.

The preview and queueing paths must compile the same immutable query and variables. Preview may wrap it in `SELECT count()` but must not modify the eventual UUID set with an implicit limit.

## ClickHouse-native queue insertion

The queueing job constructs the outer statement from trusted constants and embeds only parameterized SQL produced by the HogQL compiler:

```sql
INSERT INTO adhoc_events_deletion
    (team_id, uuid, source, source_id)
SELECT
    %(request_team_id)s,
    selected.uuid,
    'data_deletion_request',
    %(request_id)s
FROM (
    /* parameterized SQL emitted by the HogQL compiler */
) AS selected
```

The implementation must not interpolate `DataDeletionRequest.hogql_query` into this string. It parses and resolves the stored HogQL, compiles it to a single parameterized `SELECT`, and combines the compiler parameters with trusted outer parameters.

Prefer constructing the wrapper from typed query nodes if the current HogQL/ClickHouse AST supports this statement shape. If `INSERT` is not representable, a small query builder may wrap compiler-owned SQL. That boundary must accept compiled SQL plus parameters, never customer text.

The outer query owns:

- The destination table.
- The queued `team_id`.
- The `source` value.
- The `source_id` value.
- Workload and resource settings.

The inner query owns only the UUID set.

### Tenant isolation

The outer statement always writes `DataDeletionRequest.team_id`, which came from the authenticated project context. It never reads a team ID from the query result.

`deletes_job` looks up queue entries with the physical event row's `(team_id, uuid)`. If a query for team 100 returns a UUID belonging to team 200, the queue receives `(100, uuid)`. It cannot match the event stored under `(200, uuid)`.

The normal HogQL access layer still restricts what the customer can read. The composite deletion key independently restricts what the request can delete.

No join back to the events table is required. Such a join would add an expensive scan to every large deletion request without improving the composite-key tenant boundary.

## Dedicated ClickHouse principal

Introduce a `data_deletion_request_executor` principal for this operation.

It needs:

- `SELECT` privileges required by supported regular HogQL queries.
- `INSERT` on `adhoc_events_deletion`.
- No write privilege on any other table.
- No event mutation privileges.
- No DDL privileges.
- No customer-controlled query settings.
- No output-file or unapproved external table-function capabilities.

The principal must be separate from the identity used by `deletes_job`, which performs the actual mutations.

A separate user limits the impact of a parser, compiler, or query-composition defect. The executor may append deletion candidates, but it cannot mutate event storage or write elsewhere. Infrastructure must provision equivalent grants in every environment before application code depends on the new principal.

The query should run under an offline workload with server-controlled limits for execution time, memory, bytes read, temporary disk, threads, and concurrency. Settings constraints must prevent the compiled inner query from weakening those limits.

## Queue provenance

Extend `adhoc_events_deletion` with:

```sql
source LowCardinality(String) DEFAULT 'legacy',
source_id Nullable(UUID)
```

Product-created deletion rows use:

```text
source = data_deletion_request
source_id = DataDeletionRequest.id
```

`source` explains which subsystem queued the row. `source_id` identifies the exact request, which already records the actor, project, query, approval, and execution history.

These columns do not participate in the deletion dictionary key. The dictionary continues to use `(team_id, uuid)`.

The ClickHouse migration must ship in a migration-only PR. It also updates the local schema and HCL definitions so local development matches production.

## Retry and consistency semantics

An `INSERT ... SELECT` can have an uncertain result after a connection timeout or a distributed failure. Retrying the immutable request may therefore append duplicate queue rows.

The workflow treats duplicate `(team_id, uuid)` candidates as idempotent:

- `deletes_job` performs a membership lookup rather than one action per queue row.
- The dictionary input should explicitly collapse duplicate pending keys if the dictionary source does not already guarantee deterministic key selection.
- Progress and verification counts should count distinct UUIDs for the request.
- A retry reuses the same `source_id` and immutable query snapshot.
- The request moves to `queued` only after a successful queueing response.
- An uncertain failure remains retryable and never marks the request complete.

The implementation must verify how `ReplacingMergeTreeDeleted` and the dictionary handle duplicate active rows before relying on background merges. Correctness should not depend on `OPTIMIZE FINAL` running first.

Queueing fixes the selected UUID set at approval execution time. New events that match the query after queueing are not part of the request. The UI and documentation must state this timing.

## API and authorization

Add a project-nested API under `/api/projects/:team_id/` with generated request and response types. The minimal surface is:

```text
POST data_deletion_requests/preview
POST data_deletion_requests
GET  data_deletion_requests
GET  data_deletion_requests/:id
```

The server derives the team through `self.context["get_team"]()` and derives the actor and `created_by_staff` from the authenticated request. The create serializer must not accept operational fields such as `team_id`, `origin`, `created_by`, `created_by_staff`, approval state, status, or execution mode.

The API requires a dedicated destructive permission rather than general SQL-editor access. List and detail queries must filter by the current team. The product API may expose only requests appropriate for customer visibility, while Django Admin continues to expose every origin.

Preview must be rate-limited and use the normal query-cost controls. Creation must guard against replay and double submission. A client-generated idempotency key or a uniqueness constraint over an immutable submission identifier should prevent accidental duplicate requests.

## HogQL table for deletion requests

Expose product-created deletion requests as a team-scoped HogQL table named `data_deletion_requests`. This lets customers inspect and report on their requests without adding a separate product-only reporting API.

The table must:

- Apply the current HogQL team scope before returning rows.
- Expose only `origin = self_service` requests.
- Use the normal HogQL resource access controls.
- Exclude internal notes, approval comments, Dagster identifiers, and other operator-only metadata.
- Expose stable customer-facing fields such as request ID, status, query, selected count, creator, creation time, approval time, queue time, completion time, and failure state.
- Preserve `created_by_staff` so an employee acting through the product remains identifiable without changing the creation origin.

The initial schema should prefer explicit columns over a serialized model payload. Field names and status values become a customer-facing query contract once released.

The HogQL table is read-only. Creating, approving, canceling, or retrying a deletion request continues through authenticated API actions with explicit permissions.

## PostgreSQL capacity and abuse controls

`DataDeletionRequest` inherits from `UUIDModel`, which uses a UUIDv7 primary key. UUIDv7 values are time ordered, so inserts retain substantially better B-tree locality than random UUIDv4 values. The identifier itself is not expected to create material write pressure at deletion-request volumes.

The larger PostgreSQL risks are unbounded request creation, duplicate submissions, large stored queries, inefficient list and pickup queries, and indefinite retention. Apply these controls:

- Rate-limit preview and creation separately per user and team.
- Limit each team to a small number of active requests across `pending`, `approved`, `in_progress`, and `queued` states.
- Use an idempotency key for submission so retries and double clicks return the existing request.
- Cap the serialized HogQL query and variables by byte size before writing them.
- Reject unnecessary repeated previews of the same unchanged query within a short cache window.
- Index customer list access by team and creation time.
- Index Dagster pickup access by status and approval time based on the verified query plan.
- Avoid indexes on large query or variables fields.
- Define a retention or archival policy for completed and failed requests while preserving the required audit period.
- Monitor request creation rate, active rows, table and index size, and slow queries after rollout.

Enforce active-request limits transactionally so concurrent submissions cannot both pass a read-then-create check. Prefer a database-backed quota or locking strategy over an application-only count.

Index design must follow measured access paths. Before adding an index, capture `EXPLAIN` plans for the team-scoped HogQL table, customer list endpoint, approval sweep, pickup sensor, and queued verifier. Add indexes concurrently where required by the migration policy.

## Approval policy

Self-service submission and approval are separate decisions.

The current workflow can auto-approve small, closed-range event removals and leave larger requests for operator review. Query-backed requests need an equivalent policy based on a fresh preview generated by the approval job, not a count supplied by the browser.

Before launch, decide:

- Whether all self-service requests require manual approval initially.
- Which count or query-cost threshold permits automatic approval.
- Whether a maximum count blocks submission entirely.
- Whether each organization or project needs a concurrent-request limit.
- Which roles receive the destructive permission.

Regardless of policy, product-created requests always use deferred execution.

## Frontend

Add **Delete matching events** to the SQL editor save menu. Keep the action behind a feature flag during rollout.

The action is available only when:

- The current query has run successfully.
- The current editor contents match the last successful run.
- The user has the deletion permission.
- The result has one UUID-compatible column.

The confirmation dialog shows the query snapshot, match count, selection time, approval expectation, and next deletion window. It requires explicit confirmation and keeps the submit action disabled while the request is in flight.

After submission, navigate to a deletion-request detail surface showing status, selected count, submission time, approval state, queueing state, and expected deletion timing. Do not expose raw queued UUIDs.

## Activity and audit trail

Deletion requests should appear in PostHog's activity log with events for creation, submission, approval, queueing, failure, retry, and completion. Activity payloads should record identifiers and state transitions, not the full query or UUID set.

Django Admin should display and filter by `origin`, `created_by_staff`, `source_id`, actor, project, approval mode, and latest Dagster run. The two provenance dimensions remain separate throughout the request lifecycle.

## Delivery sequence

### 1. ClickHouse migration PR

- Add `source` and `source_id` to `adhoc_events_deletion`.
- Update local schema and HCL definitions.
- Verify dictionary behavior with duplicate active keys.
- Keep this PR migration-only.

### 2. Postgres model PR

- Add request origin and immutable HogQL snapshot fields.
- Define criteria-reset and immutability rules.
- Add model-level validation for query-backed event removals.
- Keep `created_by_staff` and populate it independently from the creation origin.
- Preserve compatibility with existing admin-created requests.

### 3. ClickHouse executor and infrastructure PRs

- Provision the dedicated ClickHouse principal in every environment.
- Add a credential path for the executor.
- Compile regular HogQL within the request's team and user context.
- Execute the server-owned `INSERT ... SELECT` under offline limits.
- Add provenance and retry-safe queue accounting.

Infrastructure grants should land before application code uses them. Application code should fail closed when the dedicated credentials are absent in cloud environments.

### 4. API PR

- Add preview, create, list, and detail endpoints.
- Register the team-scoped, read-only `data_deletion_requests` HogQL table.
- Add permission and tenant-scoping checks.
- Add idempotent submission.
- Regenerate OpenAPI clients.

### 5. Frontend PR

- Add the SQL editor menu action and confirmation dialog.
- Add the deletion request status surface.
- Add feature-flag and permission gates.
- Document the customer workflow.

### 6. Operational rollout

- Enable the approval, pickup, weekend deletion, and verification automation.
- Start with manual approval and a restricted cohort.
- Monitor query resource use, queue growth, failure rates, and deletion latency.
- Define rollback by disabling submission and pickup while preserving queued audit records.
- Expand eligibility and auto-approval only after observing the initial workload.

## Test strategy

### Model and API

- A request stores an immutable query and variable snapshot.
- Product creation assigns the authenticated team, actor, staff status, origin, and deferred mode.
- A staff user acting through the product produces `origin = self_service` and `created_by_staff = true`.
- Cross-team list and detail access fails closed.
- The HogQL table returns only self-service requests for the current team and omits operator-only fields.
- Customers cannot assign status, approval, origin, execution mode, or team.
- Criteria edits clear approval and preview state.
- Duplicate submissions return the existing request.
- Concurrent submissions cannot exceed the active-request limit.
- Oversized query or variables payloads fail before persistence.
- Customer list and Dagster pickup queries use the intended indexes.

### HogQL validation

- A direct `SELECT uuid FROM events` query passes.
- A UUID selected through a CTE, join, subquery, or union passes.
- Zero or multiple output columns fail.
- A non-UUID output fails before queueing.
- Invalid or unresolved HogQL fails.
- A query referencing a resource unavailable to the submitting user fails.
- Customer text cannot alter the outer insertion target, team ID, provenance, or settings.

### Queue execution

- The compiled query queues `(request.team_id, uuid)` with request provenance.
- A UUID originating from another team is still queued under the request team and cannot delete the other team's event.
- The executor cannot write to event tables or unrelated tables.
- A large selection stays entirely inside ClickHouse.
- A retry after partial insertion is idempotent.
- Duplicate active queue rows produce a valid deletion dictionary.
- Legacy and native-JSON event tables both lose queued events after `deletes_job`.

### Workflow

- Approval uses a fresh server-generated preview.
- Product requests cannot enter immediate mode.
- Queueing success moves the request to `queued`.
- Queueing failure remains retryable.
- Weekend deletion followed by verification moves the request to `completed`.

## Documentation

User-facing documentation must explain:

- The required one-column UUID result.
- Who can submit a deletion request.
- When the UUID selection becomes fixed.
- Whether approval is automatic or manual.
- When deletion normally runs.
- That deletion is irreversible.
- Which event copies and derived data the workflow covers.

Operational documentation must cover credential provisioning, resource limits, retries, queue inspection by `source_id`, schedule dependencies, and emergency shutdown.

## Open questions

1. Which product should own the backend and frontend implementation?
2. Should the HogQL table expose all self-service requests for the team or only requests visible to the querying user?
3. Which project role receives the deletion permission?
4. Do all self-service requests require manual approval for the first release?
5. What preview count or query-cost thresholds permit automatic approval?
6. Should the API accept only `HogQLQuery`, or every query node that eventually compiles to one UUID column?
7. Does the current compiler expose a safe typed representation for wrapping a compiled query in `INSERT ... SELECT`?
8. Which regular HogQL resources should the dedicated executor principal be able to read?
9. How should self-hosted deployments provision or fall back when the dedicated principal is unavailable?
10. Does the queue dictionary need an explicit `GROUP BY team_id, uuid` for retry duplicates?
11. How long should completed provenance rows remain available before the existing TTL removes them?
12. Does event deletion also need to remove or rebuild derived data outside the legacy and native-JSON event tables?
13. What customer-visible cancellation behavior is safe before UUID queueing begins and after it completes?
14. What per-user rate, per-team rate, active-request limit, payload-size limit, and retention period should apply?

## Definition of done

- An authorized customer can submit a regular one-column HogQL query without support assistance.
- The approved query snapshot cannot change before execution.
- ClickHouse selects and queues millions of UUIDs without transferring them through application memory.
- Customer input cannot control the queue destination, tenant key, provenance, or resource settings.
- The executor can write only to `adhoc_events_deletion`.
- Every queued UUID can be traced to a `DataDeletionRequest`.
- Retries cannot expand deletion beyond the immutable query and request team.
- `deletes_job` removes queued events from every active physical event table.
- The product shows the request's approval, queueing, deletion, and verification state.
- Customers can inspect their self-service requests through the team-scoped `data_deletion_requests` HogQL table.
- PostgreSQL controls bound request volume, payload size, duplicate submissions, active work, and retained history.
- Documentation and operational controls are ready before the feature flag expands.
