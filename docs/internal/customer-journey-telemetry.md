# Customer journey telemetry

A journey measures one customer action through an observed outcome. This pilot emits `customer_journey_started` and `customer_journey_finished`. Each eligible attempt has one start and at most one finish. A missing finish is an unknown outcome, not an inferred timeout.

`startCustomerJourney` snapshots organization, project, region and attempt context. It returns `null` when telemetry is unavailable or the current organization is not enrolled. Product behavior must remain independent of that result. The pure `createCustomerJourney` function owns capture, monotonic elapsed time, foreground time and terminal deduplication. Product adapters own readiness and asynchronous generation identity.

## Adapter rules

- Start before dispatching work. Reuse an existing action ID if it identifies this exact attempt; otherwise let the helper create one.
- Capture the handle/generation in asynchronous work. An old response must never satisfy a replacement attempt.
- A response, loading flag or HTTP success does not prove usable rendering. Acknowledge the matching result from its committed product surface.
- `firstUseful()` retains a timing property on the eventual finish; it emits no additional event.
- End observed failures, cancellations, replacements and teardown with their actual outcomes. Use `timed_out` only for an observed deadline/timeout. Hiding a tab merely changes foreground accounting.
- Dispose owned callbacks and listeners on completion, supersession and unmount. Do not install expensive observers for ineligible users.
- Declare `readiness_scope` and `readiness_contract_version`. Changing what counts as ready creates a different comparison cohort.
- Keep dimensions bounded. Do not add SQL, filter values, customer names, recorded DOM or error messages to these records.

## Current contracts

| Journey              | Scope                                | Meaning                                                                                                                                                                                                                                                                              |
| -------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `dashboard_open`     | `visible_product_analytics_tiles`    | Initial dashboard data loading through the fixed visible set of supported insight tiles committing usable results. Regular, streamed and supplied-dashboard paths share this contract.                                                                                               |
| `dashboard_refresh`  | `visible_product_analytics_tiles`    | A manual or automatic refresh's fixed visible set of supported insight tiles has committed its matching responses. Unsupported insight cards and duplicated saved insights are counted as excluded; widgets are not observed.                                                        |
| `experiment_refresh` | `modern_experiment_results`          | The full-results Refresh control, used while the modern results view is observed, has committed its matching responses. Metric/exposure retries, launch and automatic reloads are outside this contract. Existing exposure caching is preserved; leaving that view ends observation. |
| `replay_open`        | `player_mount_to_first_frame`        | Standard player mount to the current reconstructed frame, after successful positioning and a visible presentation opportunity. Recorded asset completion and continued playback are separate.                                                                                        |
| `person_search`      | `persons_list_query_to_table_commit` | A valid main Persons-list request has committed the matching rows or a genuine empty result. Starts after input debounce; counts and pagination are separate.                                                                                                                        |
| `sql_run`            | `sql_query_to_results_commit`        | A native full-scene SQL request, started while Results/Both is observed, has committed the matching result grid or a genuine empty result.                                                                                                                                           |

For experiments, replay, person search and SQL, `first_useful_ms` is the final readiness boundary in this slice. Only dashboards distinguish an earlier first useful tile from the whole required set.

Duplicate detection uses the complete dashboard tile inventory, including offscreen siblings. A duplicated saved insight is excluded even if only one copy is visible. The pilot retains the existing product state model; it does not fix duplicate rendering or error ownership. Refresh attempts require a complete inventory before starting. Dashboard-open attempts start before the load and fix their required set after the complete inventory and actual viewport observations arrive.

Dashboard per-type `max_duration_ms` is a maximum elapsed-to-commit time within that attempt, not a tile percentile. Dashboard finishes also include up to 50 `tile_results`, selected deterministically by numeric tile ID. Each row identifies the eligible dashboard tile and saved insight, its bounded insight type, and its observed `ready`, `failed`, or `pending` state. A ready row's `duration_ms` measures the start of its dashboard load or refresh to the matching result's committed visualization branch; it is not query-only latency or browser paint timing. Failed and pending rows never receive an inferred duration.

`tile_results_truncated` is always present with dashboard tile rows. When true, aggregate counts and per-type summaries still describe the full required set, while the rows are incomplete. Exclude truncated attempts from per-tile percentile calculations, or label them as a deterministic partial sample: selecting the lowest numeric tile IDs is stable but is not a statistical sample. For non-truncated attempts, calculate tile p95 from ready-row durations and keep failed/pending counts beside it. Per-type denominators and tile rows are finish metadata; a browser lost before finish has neither.

Dashboard opening and refresh are separate cohorts. Refresh has `manual_refresh` or `automatic_refresh` triggers. Initial opening starts when the frontend dispatches the dashboard load; application boot and any earlier variable initialization are outside this scope. It waits for the complete tile inventory, then fixes the currently visible set using real zero-margin viewport observations. Later scrolling cannot change the set. Fresh cached results can finish without a new tile request. Tiles that the product refreshes must commit the matching replacement result.

Streamed dashboards cannot fix the set until the complete inventory is known. Results already on screen are revalidated by a later readiness-prop commit. These measurements can therefore exceed the time when early streamed or cached content first became useful; they are not exact first-pixel measurements. A load with no eligible visible tiles ends `observation_stopped`, rather than reporting zero-latency success. Filter previews, individual tile refreshes and metadata-only updates are not new dashboard journeys in this contract.

Experiment child readiness counts are emitted only for a usable committed result. Earlier outcomes keep the required total and outcome details, but omit partial rendered counts because response arrival alone does not prove them.

When the exposure response explicitly reports cache status, an experiment finish includes `exposures_response_cached`. Omission means unknown. This field does not establish data freshness.

## Person and SQL request timing

Person search and SQL use `trigger: query_execution`. Timing starts after validation and local-cache guards, before concurrency admission and transport. Person typing and debounce, SQL editor startup and pre-request preparation are outside these scopes. Native SQL Run, shortcuts, suggestion/history runs and automatic execution converge on the same request path; the event does not infer which control caused a request.

A matching response must reach the actual observed table or SQL Results branch before `usable`. Empty result arrays count; missing data, malformed responses, loading placeholders, cancelled queries and errors do not. A server-returned cached result can be usable, but that does not establish freshness. Pure local-cache shortcuts do not create a request journey. Counts, pagination, live-data additions and status polling do not create additional full-query attempts.

The Persons cohort includes the enabled main plain-person ActorsQuery table, not arbitrary group or nested query sources. Requests while that table is disabled are excluded; revealing it does not adopt a previous hidden request. The SQL cohort includes the full-scene Results view and the Results half of Both. Visualization-only, BI and embedded/custom hosts are excluded. Requests before that results surface is observed are excluded rather than assigned a later start. Leaving the observed results surface stops an unfinished observation even when attached query logic remains mounted.

New full requests supersede the previous observation. Results and errors retain their own request generation; late work cannot finish the replacement attempt. Request failures and cancellations report the observed outcome, without claiming the error message painted. The SQL resource ID is an opaque editor-instance identifier, not the query text or router tab value. It does not identify a saved SQL resource across visits. These request adapters currently report bounded `query_error` failures; timeout/OOM classification needs a reliable typed signal or linked execution evidence, not error-message parsing.

## Outbound event context

The SDK adds browser URLs, session context and saved properties before capture hooks run. URLs can contain SQL or person filters. The final `before_send` hook projects only these two event names onto an explicit field list, including bounded tile summaries and the existing identity, session and group links. It removes URLs, arbitrary saved properties and profile updates. Existing caller hooks run first; their dropped events stay dropped. Other event records pass through unchanged.

There is one cross-event tradeoff: the SDK consumes initial `$set_once` attribution before this hook. If a journey consumes it first, that attribution is removed and may be absent from the next ordinary event. The pilot does not change private SDK state to restore it. Verify this behavior when upgrading the SDK, and keep journey records out of acquisition-attribution reports.

## Enrollment

The `customer-journey-telemetry` flag is off unless explicitly enabled. Its payload must have `schema_version: 1`, a nonempty `registry_version`, and `organizations` entries containing `region` (`US` or `EU`) and `organization_id`. The runtime checks the current organization and region; all its projects can participate. Keep real enrollment outside source control. Flag payloads reach browsers, so include only the required identifiers.

A synthetic payload example:

```json
{
  "schema_version": 1,
  "registry_version": "example-v1",
  "organizations": [{ "region": "US", "organization_id": "00000000-0000-0000-0000-000000000001" }]
}
```

Enable only after deployment and an internal record check. Validate each region separately. Turning the flag off prevents new starts; attempts already started keep their snapshotted context through their observed finish.

## Investigation and reporting

Join lifecycle records by region, organization, project and attempt ID, retaining scope/version. Compare like work and show sample sizes, known failures and missing outcomes alongside completed-only percentiles. Cohort by starts and allow completion look-ahead at window edges. Browser crashes, telemetry loss and never-started frontend code require separate coverage checks.

Existing ClickHouse execution spans carry physical/client query IDs for exact query-log investigation. A journey attempt ID is not automatically a trace ID: this pilot does not establish complete browser-to-backend propagation. Do not manufacture a timeline by matching nearby timestamps or a shared session.
