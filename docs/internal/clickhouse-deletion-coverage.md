# ClickHouse deletion coverage

Which ClickHouse tables a data deletion reaches, which rely on their TTL instead, and why.

Deleting a person's data is not a property of the events table.
It is a property of every table that stores rows attributable to a person.
`posthog/models/deletion_targets.py` is the one list of those tables; this document is the reasoning behind it.

## The sweeps

| Sweep                    | Entry point                     | Predicate columns                                  |
| ------------------------ | ------------------------------- | -------------------------------------------------- |
| Person deletion (async)  | `deletes_job` → `delete_events` | `team_id`, `person_id`, `timestamp`, `inserted_at` |
| Team deletion            | `deletes_job` → `delete_events` | `team_id`                                          |
| Event deletion (async)   | `deletes_job` → `delete_events` | `team_id`, `uuid`                                  |
| Queued uuid drain        | `deletes_job` → `delete_events` | `team_id`, `uuid`, `inserted_at`                   |
| Person removal request   | `delete_person_events_op`       | `team_id`, `person_id`, `timestamp`                |
| Event removal request    | `delete_event_removal_shard`    | `team_id`, `timestamp`, `event`, + HogQL           |
| Property removal request | `delete_property_removal_shard` | `properties`, `person_properties`, + HogQL         |

The first five use only columns every target declares, so they apply unchanged to any registered table.
The last two need more, which is what the capability fields on `DeletionTarget` express.

The event arm deletes one row by `(team_id, uuid)` from an `AsyncDeletion` row of type `Event`, which any Postgres writer can queue in the same transaction as its own delete.
Replay Vision writes those rows: the recording-api inserts one per `$recording_observed` event in the same statement that deletes the recording's observations, so the queue entry and the observation delete commit together.

Team deletion for tables that are replicated rather than sharded runs through a separate per-table loop (`delete_team_data_from`), which dispatches to a single host.
A sharded table must not be registered there — it would sweep one shard.
The team arm inside `delete_events` covers sharded tables.

## Reach: one handle addresses one cluster

Every sweep dispatches over a `ClickhouseCluster`, and one of those addresses exactly one cluster.
Hosts come from `clusterAllReplicas(<name>, system.clusters) WHERE name = <name> AND is_local`, and only hosts whose `hostClusterRole` macro is `data` are given a shard number.
`cluster.shards`, `map_one_host_per_shard` and `map_any_host_in_shards`, which is how every mutation reaches a storage table, enumerate those hosts alone.
Passing `data_cluster=` replaces that shard map rather than merging a second one in, so a single handle cannot span two clusters.

A Distributed table has no such limit: it routes to whichever cluster its engine names.
That asymmetry is what makes an off-cluster storage table dangerous rather than merely unsupported.
The sweep finds nothing to mutate and reports success, while the proxy every verification reads through still returns the rows.

Two gates keep that from passing silently.

- `placement_for` refuses a registered target whose storage table is on no data node of any cluster reachable from here while its Distributed proxy still returns rows (`UnreachableTargetError`). Absent from everywhere and empty is still treated as not yet migrated, which is the ordinary pre-rollout state.
- `assert_sweep_complete` runs after the immediate person-removal and event-removal sweeps and counts survivors through the proxy, so rows a mutation never reached fail the request instead of completing it (`UnsweptRowsError`).
- `deletes_job` counts the same way after its own sweep, and reports the result rather than gating on it: it marks the requests verified whether the count came back zero, non-zero, or not at all, and logs an error for the latter two. Proving zero survivors is a full scan, so each count is time-bounded and retried; see the known gap below for why the count cannot complete on `events` today. The delete predicate itself scopes the person and adhoc arms to rows with `inserted_at` no later than the request's own `created_at` (NULL counting as old), and the count shares that predicate, so what gets verified is exactly what got deleted. The bound encodes the deletion contract: a request can only name rows that were already ingested when it was made, and a row cannot be ingested before its event happened, so both `timestamp` and `inserted_at` sit at or before `created_at` for every row a request covers. A row ingested after the request is outside its scope and takes a new request to remove; without the bound, one tenant continuously ingesting backdated events for a pending deletion would block verification for all tenants. `inserted_at` is stamped server-side (`writable_events` does not expose the column), so the bound cannot be forged the way the event `timestamp` can. The team arm stays unbounded: ingestion for a deleted team stops with its token, so late rows there are stragglers the next run converges on.
- A proxy only reads the cluster its engine names, and `sql.py` builds the `events_json` proxy against `CLICKHOUSE_CLUSTER`. So a target stored on another cluster is counted twice: once through the proxy, and once on its storage table through the handle that holds it. Without the second count, a deployment whose storage moved without the proxy following it would report a clean sweep off an empty table.

Both gates probe hosts rather than compare cluster names.
Two cluster names can cover the same nodes, which is what the dev stack and CI do, so a name comparison would refuse deployments that can in fact sweep the table.
`DeletionTarget.cluster_setting` names where a storage table lives, and `ClickhouseCluster.sibling` turns that name into a handle; neither decides reachability.
`sharded_events_json` carries `CLICKHOUSE_EVENTS_CLUSTER`, which names the `events` cluster.

## Dispatching to a target's own cluster

`resolve_placements` pairs each target with the handle whose shards carry it: the job's own handle where the table is local, a sibling derived from it where it is not.
The handle in hand is probed first, so a deployment whose tables are all on one cluster never builds a second one.

Sweeps that iterate placements dispatch each target over `placement.cluster.shards`:

- `delete_person_events_op`
- `get_event_removal_shards`, which fans out one `delete_event_removal_shard` op per table and shard, so a failed delete re-executes on its own
- `deletes_job` → `delete_events`, which also has to put its dictionaries on the second cluster; see below

The rest are bound to a single handle and refuse rather than skip when a target has moved off it (`dispatchable_here`, `UnreachableTargetError`):

- Property removal. It fans out one chain of copy, delete, reingest and verify ops per table and shard of one cluster.
  Each op runs its SQL on a host of its own shard.
  Each copy records the maximum `inserted_at` it observed for that target. The copy, pre-delete count, mutation and verification reuse that bound, so a later row stays outside the destructive set.
- The deferred queue fill. Both halves of its `INSERT` are host-local: the source table it reads and the `adhoc_events_deletion` queue it writes.

### Getting the dictionaries onto the second cluster

`delete_events` does not name the rows it removes. Its predicate joins two dictionaries, `pending_deletes_<timestamp>_dictionary` and `adhoc_events_deletion_dictionary`, so a mutation cannot run anywhere those are absent.

Both reach every host of one cluster because their source table is replicated, and replication is exactly what a cluster boundary stops: a cluster with its own Keeper can never join that replica set.
`adhoc_events_deletion` compounds it, being migration-managed and present only on the main cluster.

So the rows are staged instead. One Parquet object per dictionary per run, written by the cluster itself with `INSERT INTO FUNCTION s3(...)`, and every host on the other cluster loads it through `SOURCE(CLICKHOUSE(QUERY 'SELECT ... FROM s3(...)'))`.
ClickHouse has no S3 dictionary source, but that source runs its query locally, and the query can read anything the server can.

- Nothing changes on a deployment where every target sits on the cluster the job connects to. The handle in hand is probed first, and no object is written.
- The source tables stay where they are. `pending_deletes_<timestamp>` also carries the Postgres `AsyncDeletion` row ids that `mark_deletions_verified` reads back, and those never enter a dictionary.
- `load_and_verify_deletes_dictionary` loads on every host of every cluster and fails the run unless all of them checksum alike. That is what catches a stale or missing object: without it the mutation there joins an empty dictionary, deletes nothing, and reports success.
- Retention belongs to the bucket lifecycle policy, set through `DICTIONARY_STAGING_S3_*`. Nothing deletes the objects.

The same staging carries the person-overrides squash, which is not a deletion but has the identical problem.
`squash_person_overrides` rewrites `person_id` on every table in `SQUASH_TARGETS` (`sharded_events`, `sharded_events_json` and `sharded_flag_evaluations`) through an update that joins a snapshot dictionary, then deletes the overrides it just applied.
Skipping one of those tables is worse than under-deleting: the overrides that record the correct `person_id` are gone in the next op, so the divergence is permanent.
`SQUASH_TARGETS` is derived from the `accepts_person_id_rewrite` capability rather than kept as a second hand-written list, so a target registered for deletion and then forgotten by the squash is not expressible.
Leaving one out stays possible, and `PERSON_ID_REWRITE_EXEMPT` is where that decision gets written down.
`posthog/dags/common/staged_dictionary.py` holds the piece both jobs share.

## Covered tables

- `sharded_events` — all sweeps.
- `sharded_events_json` — all sweeps, on the events cluster, through patch parts instead of mutations (`uses_patch_parts`). Optional: only present after the native-JSON migration.
- `sharded_flag_evaluations` — person, team, queued-uuid, immediate and deferred event removal, and property removal of event and person properties (below). Immediate event removal with a HogQL predicate does not sweep it, and refuses while a matching row has no events copy. Deferred event removal with a predicate reaches the rows that have an events copy through their uuids, and the rest through the predicate compiled for this table (below). Property removal with a predicate does not sweep it. Optional.
- `sharded_posthog_document_embeddings_<model>` — event and team deletion, through `delete_event_documents`. An embedded document is keyed by the id of the thing it describes (`document_id`), and an Event deletion's key is that same id, so the pending dictionary is joined on `(team_id, Event, document_id)`. Every per-model table listed by the error tracking facade's `document_embedding_tables` is swept and counted.
  A document keyed by another id is not reached by event deletion. The AI observability summaries use `<trace or generation id>::<job id>` under the `llm-analytics` product, so deleting the summary events leaves their embeddings until the table TTL.
  To remove them, turn off AI data analysis for the organization first, so no new summaries arrive during the run. Then run `delete_team_product_documents_job` with the `team_id` and the `product`. It deletes only that product's documents for that team, from the model tables and the ingestion buffer. It fails when the team has no documents for that product (a misspelled name), when the deletes run past `timeout_seconds`, or when any document survives.

Native property-removal requests fail when the selected rows retain a requested permanent or temporary property, or a matching person `$set`/`$set_once` instruction.
They also fail when that property class has quarantine diagnostics, because malformed raw data cannot prove that the requested value is absent.
The gate runs before shard processing and again during verification, with the same event, time-range, and insertion-marker bounds.

## Customer analytics membership

`sharded_person_group_membership` has no age-based TTL.
It stores distinct IDs and historical group associations, but no person properties.
The `customer-analytics-membership-discovery` Temporal schedule records missing persons and groups in Postgres.
It never deletes membership or eligibility config.
The schedule starts paused and runs hourly when enabled.
Worker restarts preserve its existing schedule settings.

Discovery checks current distinct-ID mappings and live persons.
Deleted mappings and deleted persons count as missing identities.
When ClickHouse reports a person as missing, a strong personhog read confirms the mapping and its owner.
Discovery decodes JSON escapes in group keys before identity lookups and keeps stored keys in candidates.
When ClickHouse reports a group as missing, a strong personhog read confirms its absence.
Group identity reads exclude properties. Malformed JSON keys retain their raw representation.
Decoded group keys longer than the primary identity column's 400-character limit count as missing without an identity lookup.
Scan cursors and pending membership keys use ClickHouse external tables so large stored keys do not expand SQL text.
Deleted teams need no identity reads.

Each batch scans at most 100 membership keys and rechecks 100 saved candidates.
It saves the next unprocessed key in Postgres so later batches can resume after rows disappear.
Scan pages also clear recovered candidates outside the recheck page.
Discovery checks membership for pending keys outside the scan page and removes their candidates after membership erasure.
Pending-only keys with no membership cannot create new candidates.
New candidates use bulk inserts and preserve `first_missing_at` on repeated discovery.
Identity read failures leave candidates and scan positions unchanged.
A per-team Redis lease prevents overlapping membership batches.
Discovery renews its 15-second lease every five seconds, including during network reads.
A busy lease raises a retryable error. Activity retries wait 20 seconds, so a crashed discovery worker's lease expires before retry.
Renewal failures prevent checkpoint writes. Renewal stops at the batch query deadline.
Heartbeats report liveness. Postgres stores the checkpoints.
Postgres transactions contain database writes only.

The coordinator discovers teams from membership, eligibility config, and saved scans.
It processes at most 10 pages of 25 teams and stops starting teams after 45 minutes.
Each team processes at most 100 batches and stops starting batches after 10 minutes.
The coordinator saves each processed team. Team zero holds its cursor and never starts a project scan.
Cleanup state has no project foreign key, so project deletion cannot remove pending work.

Queries use the SQL editor's `HOGQL_INCREASED_MAX_EXECUTION_TIME` setting, which defaults to 600 seconds.
Each batch reduces the query timeout to fit its remaining activity budget.
The activity reserves time for three attempts inside the child workflow deadline.
Memory, read, thread, and result limits come from the ClickHouse profile.
Unavailable shards and overflow limits fail queries instead of returning partial results.
Queries use the `OFFLINE` workload because discovery runs in the background.
Discovery queries carry the Customer analytics product tag and the data deletion feature tag.
Per-team queries also pass the team ID to the ClickHouse client so team settings and incident limits apply.
The `customer_analytics_membership_discovery_` metrics report outcomes, batch duration, and scan duration.
The scan duration includes waiting between scheduled runs. It is not the duration of one workflow execution.
Batch histograms cover durations through ten minutes. Scan histograms cover durations through seven days.
The `customer_analytics_membership_step_seconds` histogram labels each measurement by `job`, `step`, and `outcome`.
Steps separate membership scans, candidate reads, ClickHouse identity reads, primary identity checks, and checkpoint writes.
Step measurements include failed operations. Metric labels contain no team IDs or identity values.

Each `membership_discovery_batch` log includes counts, `duration_seconds`, `step_seconds`, `failed_step`, and `has_more`.
Each team and coordinator emits a `membership_run_summary` log with totals, elapsed seconds, outcome, and `stop_reason`.
Stop reasons distinguish completed work, time budgets, batch limits, page limits, failures, and cancellation.
Coordinator totals include successful child workflow results. Failed teams log their own partial totals.
Temporal adds workflow IDs, run IDs, and attempt numbers to the logs and suppresses workflow logs during replay.

Discovery does not change existing person or group deletion processes.
Membership erasure requires a separate deletion job that rechecks saved candidates before it deletes rows.
Event deletion and configured group-property deletion do not repair membership or its activity timestamps.

## Tables on TTL alone

Listed in `TTL_ONLY_TABLES`.
Each is a decision that erasure may lag by the retention window.

- `sharded_events_recent` — a transient mirror of the last few days of events, 7-day TTL keyed on `inserted_at`. It partitions by day with `ttl_only_drop_parts = 1`, so a part drops only once its newest row expires: the real worst case is about 8 days plus TTL-merge lag, not a flat 7. Short enough to accept as the erasure bound, and a sweep would race the TTL for little benefit.

Session recordings, the dead letter queue, and logs are likewise TTL-reclaimed.
That decision predates this document; the older `posthog/models/async_deletion/delete_events.py` records it in a comment, but that module is legacy and is not the source of truth here.

## Known gaps

### The survivor count is a report, not a gate

`mark_deletions_verified` marks requests verified whatever the post-sweep count says, and logs an
error when the count finds survivors or could not be taken at all. Nothing about the count stops a
run.

No branch of the delete predicate can use an index, because each one keys a dictionary on `team_id`
and a dictionary lookup is opaque to the primary key. Counting survivors on `events` therefore reads
the whole table, which exhausts every attempt against the cluster's read-bytes limit rather than its
time budget, so no larger budget changes the outcome.

Blocking on that stopped every request in the run rather than the ones at risk, and the requests it
stranded grew the dictionaries the next count had to read, so each week's stall was worse than the
last. The check is worth blocking on again once it is affordable; narrowing the count to the teams
named in the dictionaries is the reduction that makes it so.

A non-zero count is not on its own evidence the job skipped work, which is the second reason it does
not gate.

Every mutation is waited to completion before the count runs, and the person and adhoc arms of the
predicate only match rows ingested at or before their request's `created_at`. That scope closes when
the mutation finishes, so a survivor those arms still match would mean ClickHouse did not apply a
mutation it reported as done.

The team and event arms carry no such bound, deliberately, so a row can arrive after the mutation was
enqueued and still match one. A count that finds those is reading a straggler the next sweep
converges on. Failing the run on it would stall the queue on live ingestion.

So a run can mark requests verified without proving the rows are gone. What stops a sweep silently
removing nothing is upstream of the count: `MutationRunner.reuse_since` keeps a run from adopting a
mutation an earlier run enqueued, which is the failure the count was added to notice.

### Property removal on `flag_evaluations`

The property-removal job sweeps `sharded_flag_evaluations` with the same per-shard copy, delete, reingest and verify ops it runs on the events tables.
The copy writes each shard's matching rows to S3 with the named keys dropped and each affected extracted column reset, the delete removes the originals, and the reingest inserts the cleaned copy back.
That works because `materialize()` creates columns as `DEFAULT <expr>`, so an insert can set the column directly.
`DeletionTarget.accepts_property_rewrite` marks each table the job sweeps, and the gate refuses while a table without it holds rows a request names.

`group0..group4_properties` no longer exist on the table: no Insight or Hog function used them as a breakdown or a filter, so the ClickHouse team dropped them directly on both prod clusters, and `posthog/models/flag_evaluations/sql.py` no longer declares them. Event `properties` and `person_id` are still sent.
`person_properties` is on the table again, so test-account filters can read person properties off the row the way they do on `events`.
The column defaults to `'{}'`, and no row holds real person properties until the producer sends them.
Property removal treats `person_properties` here as it does on `events`: the gate counts it, the copy drops the named keys from it, and the per-shard verify, the final verify and the admin Verify count all check it.

#### Typed columns

Migration `0301_flag_evaluations_default_columns` recreated the nine typed columns as `DEFAULT <expr>`, computed from `properties` when an insert omits them.
Each carries the `column_materializer::` comment the events columns carry, on both the shard and the proxy, so the job discovers them on the `flag_evaluations` read table the same way it discovers materialized columns on `events`.
The copy writes each affected typed column as `''`, which is also what the column's expression computes for an absent key.

A request naming `$feature_flag` therefore completes: the cleaned row goes back with `flag_key = ''`, and per-flag queries stop counting it.
`flag_key` is in the table's sort key, where ClickHouse refuses any `ALTER TABLE … UPDATE` (`Cannot UPDATE key column 'flag_key'`, measured on 26.6.2), but the copy replaces the value in a `SELECT`, so the sort key is no obstacle.

The same names on `sharded_events` (`$session_id`, `$window_id`, `$group_0..4`) are true `MATERIALIZED` columns with that comment.
The copy reads the `SELECT *` shape of the table, which leaves `MATERIALIZED` columns out, and the reingest recomputes them from the cleaned `properties`.

#### Duplicate rows

`sharded_flag_evaluations` is a `ReplacingMergeTree` on `_timestamp`, like `sharded_events`, so the copies of one flag call collapse when their parts merge.
Until a merge, one uuid can have several rows.
The staged files keep every physical row.
The copy, the delete's count, the reingest and the shard verify count each uuid once, so unmerged duplicates do not block the request.
The reingest bumps `_timestamp` past the original's on both tables, so a merge that meets a cleaned row and a surviving original keeps the cleaned row.
A request that removes `$feature_flag` empties `flag_key`, which is in the sort key.
That cleaned row therefore never collapses with an original.
A table created before the switch to `ReplacingMergeTree` keeps every duplicate, and the job leaves its `_timestamp` as it is, because the job reads the engine from `system.tables` on each run.

#### Rows past the TTL

A request window can reach rows past the 92-day TTL that a part still holds, because `ttl_only_drop_parts = 1` drops a part only once its newest row expires.
The copy stages those rows like any others.
A reingested part that holds only expired rows can then drop before the reingest or the shard verify counts it.
`DeletionTarget.ttl_days` makes both checks compare only rows at least two days short of their TTL, on the table side and the staged side alike.
A part that holds one of those rows cannot drop, so every counted row is still there.
Each expired row that drops took its property with it.

#### HogQL predicates

Property removal compiles a request's predicate against the events schema only. Event removal compiles one for this table's rows with no events copy (see the HogQL section below), but property removal does not use it, so the job cannot apply a request's predicate to this table.
A property removal with a predicate leaves `flag_evaluations` out of the sweep, and `get_property_removal_shards` and `verify_property_removal` refuse the request while the table holds rows that match its other criteria.
Sweeping the table without the predicate would erase rows the predicate excludes.

#### Late arrivals

`flag_evaluations_mv` stamps `inserted_at` with `now64()` when it processes a row, as the events MV does.
A row that the consumer reads after the marker therefore falls outside the request, as on events.
The stamp comes before the Distributed forward to the shards, so a row stamped just before the marker can still reach a shard after the copy has read it.
That window is the forward delay that the events tables also have, not the consumer lag.

#### Other readers

Cleaned rows carry `inserted_at = marker`, as on events.
A reader that checkpoints `flag_evaluations` on `inserted_at` sees a rewritten row again if the marker is later than its checkpoint.
The copy carries every other column through unchanged.
`flag_evaluations_backfill_job` does not copy a day while a data deletion request run is queued or executing, so it does not re-insert an original the job removed.

`flag_evaluations` stays absent from `MATERIALIZATION_VALID_TABLES`.
The job finds typed columns through their comments in `system.columns`, not through that set, and adding the table there enrolls it in `materialize()` and the HogQL property planner, which is a separate change.

### Immediate event removal with a HogQL predicate does not sweep `flag_evaluations`

`get_event_removal_shards` leaves `flag_evaluations` out of the sweep for an immediate request that carries a HogQL predicate.
A row with an events copy ages out with the table's TTL. The table partitions by month with `ttl_only_drop_parts = 1`, so a part drops only once its newest row expires: the real wait is up to about 122 days, not the 92-day TTL.
The events copies that a deferred request deletes through do not help here, because the immediate path deletes the events rows without queueing their uuids.
A row with no events copy is checked instead.
The request refuses while such a row matches the predicate compiled for this table (below), or matches the request's other criteria when the predicate cannot run on this table.
That turns a request from an org on `flag_evaluations_mode` 2, whose flag calls have no events copy, into a refusal rather than a completed request that leaves every flag call behind.
Re-filing the request as deferred deletes those rows.
A fresh run of a request whose earlier run already deleted events also refuses, because those events were the copies of matching rows.
The admin Retry button starts such a fresh run.
"Re-execute from failure" on the earlier Dagster run finishes the request, because it reuses the output of `get_event_removal_shards` and does not run the check again.
An immediate request without a predicate sweeps the table and verifies it like the events tables, because its delete predicate names only `team_id`, `timestamp` and `event`.

### Event removal with a HogQL predicate on `flag_evaluations`

A flag-evaluation row is a fork of its `$feature_flag_called` event, with the same uuid, and both tables shard on `sipHash64(distinct_id)`, so the two copies share a shard.
`DeletionTarget.copied_from` records that relationship.
A deferred request with a predicate reaches a row that has an events copy through `events`.
The queue fill reads uuids from `sharded_events` with the events-compiled predicate, and the drain deletes those uuids from every target, so it deletes the flag row of every event the predicate names.
A flag row whose event the predicate does not name keeps its events copy and stays.

A row with no events copy needs the predicate itself.
An org on `flag_evaluations_mode` 2 stores its flag calls only in `flag_evaluations`, and a deletion that skipped the table can leave a flag row whose event is gone.
`DeletionTarget.uncopied_rows_hogql_table` names the HogQL table that compiles the predicate for those rows, `posthog.flag_evaluations` here.
The compile adds that table even when the org's mode hides it from queries.
The queue fill reads the uuids of the rows with no copy in `sharded_events` that the compiled predicate matches, shard-locally and in 7-day windows, and queues them with the rest.
A row read this way already existed when its uuid was queued, so the drain's `inserted_at` bound cannot skip it.
The check for an events copy reads `sharded_events` only.
In production, `sharded_events_json` holds no `$feature_flag_called` rows: the deployed ingestion view and the backfill both leave the event out, so a flag row has no copy there.
The view this repo defines (`EVENTS_JSON_TABLE_MV_SQL`) still writes the event, so local, CI and self-hosted deployments do keep a copy.
There, a flag row can keep its `sharded_events_json` copy after its `sharded_events` copy is gone, when an earlier immediate request matched the two events tables differently.
Queueing that row would also delete its `sharded_events_json` copy, even when the native-JSON compile of the predicate excludes it, because the drain deletes a queued uuid from every target.
The check cannot look for that copy row by row, because `sharded_events_json` can sit on another cluster, where a shard-local subquery cannot reach it.
So before a deferred request queues rows with no `sharded_events` copy, the gate counts the flag calls in the request's window on `sharded_events_json`.
It counts through the `events_json` proxy, and also on the storage table through its own handle when that table sits on another cluster, because the proxy can read an empty table there.
When it finds any, the request refuses while a row with no `sharded_events` copy matches the compiled predicate.
Production stores no flag calls in `sharded_events_json`, so the gate finds none there.

The compiled predicate never decides for a row that has an events copy.
The drain deletes a queued uuid from every target, so a flag row that matched the flag-compiled predicate would take its events copy with it, even where the events-compiled predicate does not name that event.
The two compiles can disagree.
On cloud, `propertyGroupsMode` is `optimized`, and events reads a custom property, an `$ai_` property or a `$feature/` property from a property-group map such as `properties_group_custom`.
The map is built with `JSONExtractKeysAndValues(properties, 'String')`, which decodes JSON escapes, so a stored `"a\"b"` reads as `a"b`.
For `=`, `!=` and `IN`, the `optimized` rewrite also compares a typed property as a string.
`flag_evaluations` has no property-group map, so it reads the raw JSON with the surrounding quotes stripped, which reads `a\"b`, and it casts a typed property to its defined type.
On cloud, events reads some `$` properties from `mat_` or `dmat_string_` columns instead, and those differ on edge values: the column reads an empty string and the string `"null"` as NULL, and a nullable column decodes escapes.
So with `$browser` materialized, `properties.$browser = ''` excludes a row that stores `""` on events and matches it on `flag_evaluations`.
The compile therefore refuses a predicate whenever the events compile of it reads a property-group map or a materialized column.
Every property the compile accepts reads raw JSON on both tables.
It also refuses one that needs a join, such as `person_id`, because the fragment is spliced into a bare WHERE that has no join.
`person.properties` and `elements_chain` do not resolve on the table, so those predicates fail to compile.

When the predicate cannot run on the table, the gate counts the rows with no copy in `sharded_events` that match the request's other criteria, shard-locally, and refuses the request when it finds any.
Requests without a predicate, immediate or deferred, are swept normally.
A deferred one reads the table's own uuids into the queue.

Verification of a deferred request with a predicate, when the table holds rows in the request's window, makes two counts.
The first is the request's queue rows that the drain has not marked deleted.
The second is the table's rows with no copy in `sharded_events` that the compiled predicate matches, or that match the request's other criteria when the predicate cannot run on the table.
The queue rows hold the request until `deletes_job` drains them, including a queued row whose event a property removal changed so that the predicate no longer matches it.
The rows with no copy hold the request after the drain.
A flag row stamped after its events copy's uuid was queued falls outside the drain's `inserted_at` bound, so it survives the drain.
The drain still deletes its events copy.
The rows with no copy therefore include it and keep the request in QUEUED.
A re-filed request does not reach that row.
A deferred one queues the uuid, but the drain skips it while the first drain's `is_deleted` marker lasts, which is 3 months.
Only an immediate request without the predicate deletes the row, and it also deletes every other row in its window that its event filter names.
The verify sweep therefore keeps checking a deferred request with a predicate for `lookback_days` after its window falls behind the table's TTL horizon, so the request moves to COMPLETED once the TTL drops the row.
The rows with no copy also keep a request the gate refused, which queued nothing, from passing verification as a FAILED request.
Counting every row that matches the request's other criteria would hold the request in QUEUED until the TTL, whenever the team has flag calls the predicate does not name.
The second count uses the same compiled predicate as the queue fill, so it cannot see the two compiles disagreeing.
The compile's refusals are the guard against that.

## Producer prerequisite: person_id parity

Every person sweep is keyed on `person_id`, on `flag_evaluations` as on events.
That is only correct because the producer populates `person_id` for every row, exactly as the events ingestion pipeline does: the resolved `Person.uuid`, or a deterministic per-`distinct_id` uuid when no person was resolved.
The shadow-routing producer (`posthog-code/flag-evaluations-shadow-routing`) forks the enriched event downstream of person resolution, so it inherits that value for free.

If a future producer emitted rows before person resolution, leaving `person_id` unset, a person deletion would strand them.
The fix would belong to the producer, not the scanner.
Keeping the fork downstream of person resolution is the contract, tracked on #81002.

Write-time parity is not sufficient on its own, because a later merge moves the person the sweep looks for.
After person A merges into B, a deletion of B is queued under B's uuid, so any row still carrying A matches nothing and survives with its event `properties` and its stale `person_id` until the TTL drops the part.
`sharded_flag_evaluations` is a squash target as well as a deletion target for that reason: it sets `accepts_person_id_rewrite`, and `person_id` is not in its sort key, so it takes the same `ALTER UPDATE` `sharded_events` takes.
A target that leaves the capability unset strands its rows permanently, because the squash deletes the overrides that recorded the mapping right after applying them.
Rows a merge stranded before `sharded_flag_evaluations` joined the squash age out with their partition.

`flag_evaluations_backfill_job` (`posthog/dags/flag_evaluations_backfill.py`) is a second producer.
It copies `person_id` from `sharded_events`, so its rows meet the same parity.
It leaves `inserted_at` to the column default, which is the event `timestamp`, so every copied row sits inside the `inserted_at` bound of any request made after its event.
It does not copy a day while a `squash_person_overrides`, `deletes_job` or data deletion request run is queued or executing.
A day copied during one of them can read a row before the job rewrites it and insert it after the job sweeps `sharded_flag_evaluations`, which keeps what the job removed.
When one of those runs starts during a copy, the shard stops, and its error names the rows to delete before the backfill runs again.

## Related, and deliberately unchanged

`_fetch_stats` counts only the events tables. It feeds `AUTO_APPROVE_MAX_EVENTS`, a cost heuristic rather than a completeness claim, so a request auto-approved as small may move somewhat more rows than measured.

`cleanup_old_events_by_partition` stays events-only. It enforces the events retention that staff set for each team.
The sessions tables are built from events and have no TTL, so `cleanup_old_sessions_by_partition` deletes them with the same retention after the events are gone.
In deployed cloud they are `sessions` (v1), `raw_sessions` (v2) and `raw_sessions_v3` on the sessions satellite cluster, named by `CLICKHOUSE_SESSIONS_CLUSTER`.
Elsewhere they are `sharded_sessions`, `sharded_raw_sessions` and `sharded_raw_sessions_v3` on the main cluster.
The job skips any of these tables that does not exist.
Other personal-data tables expire sooner under their own TTL.
It deletes a month only when every event in it is older than the retention. A month that is only partly past the retention waits for a later run, for manual runs too.

Organization admins set the retention in project and organization settings, and staff set it in Django admin, on the team and organization pages:

- `OrganizationEventsRetentionConfig` holds the organization's default, minimum and maximum months.
- `TeamEventsRetentionConfig` holds a team's own months, which must fall within its organization's range. Saving an organization range that excludes an existing team value fails until that team changes.
- A team's set period is its own value, else its organization's default. A set period is deleted at every run.
- A team with no set period uses its default period, which waits for the team's pass, every 3 months.
- The default period is the plan's period, capped at 24 months when the organization has the `product_analytics_standard_data_retention` feature. Billing gives that feature to current plans only, so older plans default to their whole period. The default never goes below the organization's minimum.
- `Team.event_retention_months` is the plan's period, which billing sets. A period never deletes past it before the team's pass.
- The Events retention page under Custom tools (`/admin/events-retention/`) lists every team that has a value of its own or belongs to an organization with a config.
  It shows each team's billing months (`Team.event_retention_months`), its effective retention, where that comes from, and the first month the cleanup keeps, 100 teams per page.

`monthly_retention_events_cleanup_job` has six steps:

- `update_plan_deletions` tracks each team's pass period in `TeamEventsPlanDeletion`: the set period, never past the plan's period, else the default period. It gives a row only to the teams where `should_delete_past_default_period` is true, and removes the rows of all other teams. A team without a row gets no pass, and its set period is never capped by its plan.
  - `should_delete_past_default_period` needs the `events-data-retention-deletion` flag on PostHog Cloud, and does not depend on query enforcement. Self-hosted never gets a pass. The flag gets each team's plan period and organization, so a rollout can target plans and leave out organizations.
  - A new row's first pass is at least 3 months out, so a team keeps its events for at least 3 months after the flag turns on.
  - Turning the flag off removes the team's row at the next run. A run that already finished `update_plan_deletions` still deletes for that team.
  - A shorter period, from a downgrade or a change in Django admin, moves the team's next pass to at least 3 months out.
  - It locks the rows of 1000 teams at a time, reads their periods, and writes its changes in one transaction. A period saved in settings during the run is therefore kept. It then hands on the teams whose pass is due.
- Saving a period in settings writes the row of each team that deletes past its default straight away, so the settings page can show the next deletion. A shorter period moves the next pass to at least 3 months out. The save writes the rows before and after it changes the period, so a row that still holds a period from before a plan change first catches up to the period in use.
- The cleanup and settings write rows through `reschedule_plan_deletions`, which locks the rows before it reads the periods.
- Pass dates fall on the 3rd, so the date shown is the run that deletes.
- `plan_old_events_cleanup` reads every team's set period. A team with a set period uses it. A team whose pass is due uses its pass period, or the shorter of the two. It reads each due pass row again, so a period saved after the run started applies: a longer period raises the row's months, and a shorter one moves the pass past this run. It logs each team's period in months, then finds the months that hold events for each team and keeps the ones entirely past that team's period. It logs the teams due in each month.
- `cleanup_old_events_by_partition` deletes each planned month for the teams due in that month only. A team with 13 months and a team with 18 months share the older months, and the 13-month team also has months of its own.
- `plan_old_sessions_cleanup` starts after the events are deleted. It uses the period the events plan used for each team, and finds the sessions partitions entirely past it, so a month whose events an earlier run deleted still gets its sessions deleted.
- `cleanup_old_sessions_by_partition` deletes each planned sessions month for the teams due in it. Sessions partition by the month a session started, so a session that continues into a kept month is deleted with the due month.
- `advance_plan_deletion_passes` moves the next pass of each team that both plans completed 3 months out, after the sessions deletes succeed. It keeps a later date that a shorter period saved during the run set.

A manual run can narrow each plan with its own `team_ids` and `partitions`. The sessions plan covers only the teams the events plan covers. A listed team with neither a set period nor a pass due is ignored.
A pass completes only for a team that both plans include, and only when neither sets `partitions`. Otherwise the pass stays due for the next full run.
The `update_plan_deletions` config has its own `team_ids`, which limits the rows it adds and removes.
`monthly_retention_events_cleanup_schedule` starts one run on the 3rd of each month at 21:00 local time (Europe/Paris in EU, America/Los_Angeles elsewhere). It is stopped by default.
Pass dates are dates in that local time zone, so the date shown in settings is the day its deletes start.

A billing sync that lengthens the plan period writes the organization's rows straight away, so a downgrade soon after still sees the longer period.
A billing sync that shortens the plan period checks each team's period under the previous and the new plan, each with its own standard retention feature.
It does nothing more when no team's period gets shorter, for example when every team has a set period within the new plan.
Otherwise it writes the rows of those teams straight away, the same way a settings save does.
The sync then queues the Celery task `report_events_retention_shortened`, which sends an `events retention period shortened` event to each organization admin, with the previous and new plan periods and the first pass past the shorter period.
That pass date is empty when the deletion flag covers none of those teams.
The send runs in a worker, so an ingestion outage never holds up the billing sync, and the task retries a failed send 5 times over up to about 15 minutes.
The first billing sync of a new organization sends nothing, because the organization has no previous plan period.
The Celery beat task `report_upcoming_events_deletions` runs daily at 15:00 UTC.
On the day the next cleanup is exactly 14 days away, it reschedules the rows due at that cleanup, the same way a settings save does, so a period that got shorter since the pass was set moves the pass instead of announcing it.
It then sends an `events retention deletion upcoming` event to the admins of each organization with a team still due, one organization at a time, whether the team downgraded or not.
Every pass gets this event, every 3 months, and only teams behind the deletion flag have rows, so a team that joins the flag after a downgrade hears before its first pass.
A team whose set period is at or below its pass's period is left out, because the monthly cleanup already deletes everything that pass would.
A set period above the pass's period still sends.
Only that one day sends, so nothing records what was sent.
A failed send fails the task, which retries the same way as the shortened task, and a retry sends again to the organizations already sent.
Workflows turn both events into emails.

The job runs `ensure_no_concurrent_deletes_run` before it plans, and that guard also runs in `deletes_job`. Each job fails at the start while a `deletes_job`, cleanup or squash run is executing, so the two never mutate the events tables at the same time.
Both jobs and `squash_person_overrides` carry the `deletes_job_concurrency` tag. The Dagster deployment settings put a run-queue limit of 1 on that tag, so a second run of any of the three queues instead of starting.
`sharded_events_json` keeps events dated before 2020, because it stores them in its 202001 partition and the delete addresses the event's own month.

## Adding a table

Register it in `PERSONAL_DATA_TARGETS`, with capability flags reflecting what its schema can actually take and what the sweep code actually implements: `accepts_property_rewrite` makes the property-removal job sweep the table, so it needs a rewrite that cleans every copy the table keeps, not just assignable columns, and a `person_properties` column, because the job reads and rewrites that column on every table it sweeps.
Set `accepts_person_id_rewrite` unless you mean to leave the table out of the squash, which needs `person_id` outside the table's sorting and partition keys; skipping it is what stranded `flag_evaluations` rows on a merged-away person (#93035).
A table you do leave out goes in `PERSON_ID_REWRITE_EXEMPT` with the reason.
If it is not going to be swept, add it to `TTL_ONLY_TABLES` with the window you are accepting.
If its storage lives on a cluster other than the one the deletion jobs connect to, give it a `cluster_setting` naming that cluster and mark it `optional`; see "Reach" and "Dispatching" above for which sweeps then reach it and which refuse.

`posthog/clickhouse/test/test_deletion_coverage.py` fails on any storage table that declares `person_properties` and appears in neither deletion list, so that decision has to be made rather than skipped.
It fails the same way on a registered target that neither sets `accepts_person_id_rewrite` nor appears in `PERSON_ID_REWRITE_EXEMPT`, and on a squash target carrying `person_id` in its sorting or partition key.
It also fails on a `PERSON_ID_REWRITE_EXEMPT` entry that names a squash target or a table no target registers, so the list holds only exemptions that are still in force.
