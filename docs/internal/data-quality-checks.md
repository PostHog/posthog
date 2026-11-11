# Data quality checks

Data quality checks audit warehouse tables, saved views, catalog metrics, and the PostHog tables `events`, `persons`, and `groups`. Checks keep their identity and history when their assertion changes.

## Authorization

Every check is authored, read, run and scheduled through the project-wide `data_quality_checks` and `data_quality_runs` routes, whichever kind of subject it audits. A request names its subject in the body on create, and by check id after that; `subject_type` and `subject_uuid` query parameters narrow a listing, a health rollup, a run history, or a schedule to one subject. A PostHog table has no database row, so its `subject_uuid` is a fixed id derived from the table name and is the same in every project.

Check and run routes require project membership, query access, and access to the subject. The static check-type catalog needs no access to any subject. Metric checks use catalog permissions. Table and view checks use their respective warehouse object permissions, including explicit object grants and inherited source grants. A PostHog table has no object to grant, so a check on one answers to project query access and the warehouse table resource level. A failing check on a PostHog table notifies members with query access and links to the data quality overview, because these tables have no page of their own. A resource-wide denial does not discard a more specific grant that the canonical access-control rules permit.

Reading checks, health, and run history requires viewer access. Creating, editing, deleting, or manually running checks requires editor access to their subject. Referenced subjects require viewer access. These checks apply even when the warehouse query-enforcement feature flag is disabled.

Checks and suites are polymorphic: a catalog-only member can read a teammate's metric checks without warehouse access. Project lists filter by each row's subject. A mixed suite is hidden if any recorded run is unreadable, because aggregate counts would otherwise disclose its outcome.

Restricted callers must have access to both the stored and proposed definitions before PUT or PATCH can save anything, including presentation-only edits. Authorization is repeated if a concurrent edit changes the definition accepted by the transaction. An edit makes three attempts. After three attempts it writes nothing and returns HTTP 400 with the code `concurrent_edit`. An unavailable reference fails closed. An authorized caller can still disable a stale check without revalidating its assertion.

A check that reads more than its own subject executes as a user, and so does every check on a PostHog table, because property restrictions and warehouse joins on those tables resolve per user. A manual run executes as the user who started it, and an automated run executes as the user who last wrote the definition. If neither user is available, the run records an error and executes no SQL.

A check on a PostHog table names a column the registry lists for that table. A dotted name reaches into a JSON column only, so `properties.$browser` is accepted and `person.properties.email` or a warehouse join is refused at authoring time. The same rule applies to the `to_column` of a relationships check that points at a PostHog table.

## Token scopes

All routes below also require `query:read`. Write scopes include read access; read-only scopes do not authorize writes. Token scopes limit access independently of the user's grants, including for organization administrators.

| Subject kind                        | Read scope                                         | Write scope                                          |
| ----------------------------------- | -------------------------------------------------- | ---------------------------------------------------- |
| Warehouse tables and PostHog tables | `warehouse_objects:read` or `warehouse_table:read` | `warehouse_objects:write` or `warehouse_table:write` |
| Warehouse views                     | `warehouse_objects:read` or `warehouse_view:read`  | `warehouse_objects:write` or `warehouse_view:write`  |
| Catalog metrics                     | `data_catalog:read`                                | `data_catalog:write`                                 |

The family scope `warehouse_objects` reaches every warehouse kind. A per-kind scope reaches its own kind only, which is what a key minted by the Agent CLI carries. A token may select only the subject kinds its scopes permit. An unnamed manual sweep skips inaccessible checks; an explicitly selected inaccessible check is rejected. Cross-subject references must also fall within the caller's permitted subject types.

The table above applies to the REST routes only. The MCP tools declare `query:read` alone, because a tool's scope list must be met in full and the two subject families are authorized independently; a token with no subject family is refused by the route. A raw HogQL query against `system.information_schema.data_quality_*` needs `query:read` and no other scope. The user's own permissions still apply to each row. A token with `query:read` reads metric checks only if its user has catalog access.

## Question execution foundation

The question execution primitives in `products/data_quality/backend/logic/jev_*.py` are not yet registered as an authorable check type.
They provide the warehouse-table execution foundation before the check registry, Temporal orchestration, durable run checkpoints, previews, and editor are wired.
`WarehouseQuestionExecutor` connects source preparation, manifests, Redis, and the gateway.
Its caller supplies atomic persistence callbacks for manifest selection and checkpoints, plus a durable reservation for inference inputs.
Query and inference tags carry check and run identifiers without source values.

`QuestionConfig` accepts a column input or explicitly selected row fields, a yes/no assertion, an inclusive minimum probability (default 0.8), and an inclusive allowed failure rate (default 0).
Row fields are sorted by label and serialized with their types and explicit null values.
NaN and infinities serialize as quoted strings, so they stay distinct from null.
Column nulls contribute deterministic row failures without inference.
Nulls do not contribute to the decision counters.
Warehouse fields must appear in the subject's column catalog, and the projection is compiled as the executing user after checking subject access.

The source query groups exact evaluator inputs and preserves their row multiplicities without a row limit.
It streams bounded chunks into the configured object store and publishes a manifest only after the source stream completes.
ClickHouse overflow settings throw instead of returning partial results.
A response that ends before the Arrow end-of-stream marker, or has data after it, fails before any manifest is published.
A subject that exceeds the limit on frozen inputs fails before any manifest is published.
A manifest freezes the definition, the explicitly supplied model revision, and the evaluator contract version.
A deployment with a different evaluator version rejects the manifest and its checkpoints.
A retry must reuse that manifest; a new run must prepare a new one.
Empty manifests skip.

Redis keys are project-scoped hashes of the exact input, question schema, model id, immutable model or deployment revision, and evaluator contract version.
Thresholds are excluded.
Only validated probabilities and their revision, evaluator version, and timestamp enter the cache.
The default TTL is 30 days and reads do not renew it.
Malformed or expired entries miss; Redis errors stop evaluation.
Leases use ownership tokens, bounded renewal that outlasts the inference wait, and atomic publication and release.
A crash between the model response and cache publication can still cause duplicate billed inference.
So can a failed gateway batch: the runner waits for every batch in a chunk, so one failure discards the decisions the other batches already returned and the retry pays for them again.

The chunk evaluator reuses `PromptJevRunner` and the billed gateway.
Chunk limits, an inference input budget, and execution deadlines raise errors with incomplete coverage; they never produce a successful result from fewer rows.
Checkpoint callbacks must atomically retain the first result under `(run, chunk)`.
Finalization counts each checkpoint once and verifies total row and input coverage before evaluating the failure rate.

Before enabling this path in the checks system, persist manifest references and chunk checkpoints through the checks models, reserve the inference budget durably across activity retries, and add object-store lifecycle cleanup for expired or abandoned prefixes.
The caller must resolve an immutable model revision, or configure a deployment revision that changes with the served model.
Authorization must run before replaying any checkpoint or reading decisions.
The run deadline is checked before every chunk and before the final result, so a replayed checkpoint or a fully cached chunk cannot outlast it.
An inference reservation is spent only after the gateway accepts the run, so a disabled flag, an exhausted credit budget, or a missing gateway leaves the allowance untouched.
Staged views, PostHog tables, warning-only authoring, and results UI require the subsequent integration.

## Lookback window

A check may carry `lookback_hours`, which counts only the rows from the last N hours by the subject's own time column.
It is optional.
Without it, a check reads every row the subject holds.
Only the PostHog tables carry a time column today: `events` bounds on `timestamp`, and `persons` and `groups` bound on `created_at`, which is when each was first seen rather than when it last changed.

A `relationships` check bounds each side on its own, with `lookback_hours` for the rows it checks and `to_lookback_hours` for the rows it looks for a match among.
Custom SQL takes no window, because bounding a query the author wrote would mean rewriting it. Put the filter in the query instead.
A window named for a subject or a target that has no time column is rejected when the check is saved.
A query that runs too long is recorded as `errored` with the message the database returned.

## Custom SQL

Custom SQL supports direct relations, subqueries, CTEs, and unions. Metric checks bind `{metric}` before enumerating dependencies. Metric checks cannot use CTEs. Query `{metric}` directly or through a subquery. Expandable table expressions whose dependencies cannot be established, including HogQLX sources and table functions, are rejected during authoring and compilation.

Previously saved definitions that cannot be enumerated remain hidden and unrunnable for restricted callers. Execution permissions do not replace the checks that protect definitions, counts, and history.

## History and discovery

A run is authorized using the subject identities recorded when it executed. Editing a check does not authorize its earlier results. Deleted subjects, unreadable recorded references, and missing dependency records on cross-subject checks remain inaccessible. An authorized edit can return the updated check with historical status fields redacted.

The REST endpoints and `information_schema.data_quality_checks`, `information_schema.data_quality_check_runs`, and `information_schema.data_quality_health` share visibility rules. Their query-cache boundary includes catalog, warehouse, and source permissions.

The overview filters readable subject identities in SQL before scanning definition and history visibility. The remaining scan loads only authorization fields in batches of 200 checks, before counting or paginating. Creator and owner records are hydrated for the returned page. Complex-definition evaluation still scales with the candidate checks; pagination is not constant-cost.

Notification recipient checks retain the existing global warehouse-resource policy. A specific object grant alone does not expand notification delivery eligibility. A subject that no longer resolves sends no notification. Background dependency pinning still resolves references individually; batching that cross-product workflow is separate work.

Catalog access is a project permission resource. Notification visibility follows that permission, including after access is revoked.

A run under the materialization gate sets `audited_staged_refresh`, including a run that errored before it could read the staged files. Check `status` and `error` before treating the refresh as audited. The stored failing-rows query cannot name the view, because the SQL editor resolves that name to the published table, which after a block is still the previous version. So the query holds the view's definition in a `WITH` clause and reads the view's source tables. Those sources can change after the run, so a replay can return different rows than the run counted. When the view's definition cannot be read, the run stores no query.

## Models overview

The models overview reports one status for the whole project. It shows the status panel only when the model list and the check list have both answered, and when no model and no check needs attention. A request that failed is reported as a failure, so an unanswered request never reads as an all-clear.

The panel's text follows the check results. It claims that all data quality checks passed only when every check passed on its last run. A check that was skipped or has never run is not a passed check, so the panel then says that no checks are failing and some have not passed yet. The overview reads one page of checks, so a project that fills that page gets the same text as a project with the data quality tab off: a check on a later page could be failing. A project with no checks is asked to add some. When the data quality tab is not available, the panel speaks about the models alone.

A project that has no models and no saved views gets the first-view text instead of a status claim.

## Model detail

Every table node keeps its Lineage tab. Loading the Data quality subject does not wait for the lineage graph.

A model in the lineage graph can also open a Data quality tab. The tab reads the checks of the model's own subject. A saved view answers as a view. An imported warehouse table answers as a table. The node carries the table identifier. The dependency sync refreshes this identifier when it resolves a saved query. A table that is deleted and imported again then uses its new row.

PostHog tables use the subject catalog API. The frontend matches the node name to a `posthog_table` subject from that API. It passes the returned subject id, subject type, and columns to the checks panel. It does not calculate the subject id. The Data quality panel shows a loading, request-error, access-denied, or unsupported-table state when the catalog cannot provide a supported subject.

## Subject schedules

A subject whose checks run on a recurring schedule has one Temporal Schedule in its canonical project. Metrics and PostHog tables are those subjects; a warehouse table's and a view's checks run when their data changes instead. A PostHog table is never synced or materialized, so a schedule is the only trigger its checks have. The first check creates an enabled daily schedule after the check transaction commits and starts an initial run. Available intervals are one hour, six hours, twelve hours, one day, and one week. A deterministic offset spreads recurring executions across each interval.

Temporal owns the interval, pause state, and next execution time. The schedule endpoint reads and updates Temporal directly. Paused schedules return `next_run_at: null`. An unavailable schedule service returns HTTP 503; reload the schedule before retrying an update whose outcome is unknown. Last scheduled run information comes from the caller's readable suite history. Manual runs do not change it.

Scheduled executions skip an occurrence when the previous scheduled workflow is still running. Temporal catches up missed occurrences within 15 minutes and does not pause a schedule after a failed run. Manual runs keep their existing behavior. A scheduled activity rechecks schedule existence and pause state before selecting current enabled checks. An executing check can finish after the schedule is paused. Feature flags, subject existence, and execution permissions are checked in activities.

A reconciler runs every 15 minutes, processing bounded pages of checks and product-filtered Temporal schedules. It performs up to 10 independent repairs or deletions at a time within a page, then advances only after the whole page succeeds. It repairs missing schedules without changing existing intervals or pause states, and deletes schedules whose subject no longer exists. Deleting or disabling all checks retains the metric's schedule preferences and executes no check queries. Deleted metrics stop producing check queries immediately, even if schedule cleanup needs a retry.

In the metric Tests tab, a failed schedule edit refreshes the persisted state and offers Reload before another edit. Schedule controls stay disabled while a request is pending or its outcome is uncertain.

Background schedule refreshes preserve a newer edit response, so a pending refresh cannot undo the settings shown after an edit.
