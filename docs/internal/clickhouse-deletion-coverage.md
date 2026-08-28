# ClickHouse deletion coverage

Which ClickHouse tables a data deletion reaches, which rely on their TTL instead, and why.

Deleting a person's data is not a property of the events table.
It is a property of every table that stores rows attributable to a person.
`posthog/models/deletion_targets.py` is the one list of those tables; this document is the reasoning behind it.

## The sweeps

| Sweep                    | Entry point                      | Predicate columns                          |
| ------------------------ | -------------------------------- | ------------------------------------------ |
| Person deletion (async)  | `deletes_job` → `delete_events`  | `team_id`, `person_id`, `timestamp`        |
| Team deletion            | `deletes_job` → `delete_events`  | `team_id`                                  |
| Queued uuid drain        | `deletes_job` → `delete_events`  | `team_id`, `uuid`                          |
| Person removal request   | `delete_person_events_op`        | `team_id`, `person_id`, `timestamp`        |
| Event removal request    | `execute_event_deletion`         | `team_id`, `timestamp`, `event`, + HogQL   |
| Property removal request | `process_property_removal_shard` | `properties`, `person_properties`, + HogQL |

The first four use only columns every target declares, so they apply unchanged to any registered table.
The last two need more, which is what the capability fields on `DeletionTarget` express.

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

Both gates probe hosts rather than compare cluster names.
Two cluster names can cover the same nodes, which is what the dev stack and CI do, so a name comparison would refuse deployments that can in fact sweep the table.
`DeletionTarget.cluster_setting` names where a storage table lives, and `ClickhouseCluster.sibling` turns that name into a handle; neither decides reachability.
`sharded_events_json` carries `CLICKHOUSE_EVENTS_CLUSTER`, which names the `events` cluster.

## Dispatching to a target's own cluster

`resolve_placements` pairs each target with the handle whose shards carry it: the job's own handle where the table is local, a sibling derived from it where it is not.
The handle in hand is probed first, so a deployment whose tables are all on one cluster never builds a second one.

Sweeps that iterate placements dispatch each target over `placement.cluster.shards`:

- `delete_person_events_op`
- `execute_event_deletion`, immediate mode
- `deletes_job` → `delete_events`, which also has to put its dictionaries on the second cluster; see below

The rest are bound to a single handle and refuse rather than skip when a target has moved off it (`dispatchable_here`, `UnreachableTargetError`):

- Property removal. Its staging table is host-local and its fan-out is one op per shard of one cluster.
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
`squash_person_overrides` rewrites `person_id` on `sharded_events` and `sharded_events_json` through a mutation that joins a snapshot dictionary, then deletes the overrides it just applied.
Skipping the second table there is worse than under-deleting: the overrides that record the correct `person_id` are gone in the next op, so the divergence is permanent.
`posthog/dags/common/staged_dictionary.py` holds the piece both jobs share.

## Covered tables

- `sharded_events` — all sweeps.
- `sharded_events_json` — all sweeps. Optional: only present after the native-JSON migration.
- `sharded_flag_evaluations` — person, team, queued-uuid and event removal. Not property removal (below). Optional.

## Tables on TTL alone

Listed in `TTL_ONLY_TABLES`.
Each is a decision that erasure may lag by the retention window.

- `sharded_events_recent` — a transient mirror of the last few days of events, 7-day TTL keyed on `inserted_at`. It partitions by day with `ttl_only_drop_parts = 1`, so a part drops only once its newest row expires: the real worst case is about 8 days plus TTL-merge lag, not a flat 7. Short enough to accept as the erasure bound, and a sweep would race the TTL for little benefit.

Session recordings, the dead letter queue, and logs are likewise TTL-reclaimed.
That decision predates this document; the older `posthog/models/async_deletion/delete_events.py` records it in a comment, but that module is legacy and is not the source of truth here.

## Known gaps

### Property removal does not reach `flag_evaluations`

The events property-removal path rewrites rows in a staging table and resets each affected materialized column with `ALTER TABLE … UPDATE <col> = ''`.
That works because `materialize()` creates columns as `DEFAULT <expr>`, which is assignable.

All of that machinery (column discovery, staging rewrite, shard walk) is scoped to `events`; none of it reaches `flag_evaluations`.
Until it does, `get_property_removal_shards` refuses to start when the table holds rows matching the request, so a request cannot complete while data it named survives.
The check costs nothing while the table is empty.

The schema stopped being a second obstacle with migration `0301_flag_evaluations_default_columns`, which recreated the nine typed columns as `DEFAULT <expr>`, the kind `materialize()` mints on events; they were true ClickHouse `MATERIALIZED` before, which is not assignable at all.
Measured against ClickHouse 26.6.2 on the `DEFAULT` shape:

- `CREATE TABLE` accepts a `DEFAULT`-from-`properties` column (`flag_key`) in the sort key, and an insert that omits the typed columns computes them from `properties`.
- Assigning to a non-key typed column is accepted: `ALTER TABLE … UPDATE session_id = ''` completes. Under `MATERIALIZED` it was rejected with `Cannot UPDATE materialized column 'session_id'`.
- Updating `properties` is accepted, alone and in the events-path form that resets affected typed columns in the same mutation.
  The `MATERIALIZED`-era rejection (`Updated column 'properties' affects MATERIALIZED column 'flag_key', which is a key column`) does not fire for `DEFAULT` dependents.
- An `UPDATE` of `properties` does not recompute the typed columns; rows keep their stored values.
  The rewrite must reset each affected column explicitly, exactly as the events path already does.
- `flag_key` itself can never be reset: `ALTER TABLE … UPDATE flag_key = ''` is rejected with `Cannot UPDATE key column 'flag_key'` (`CANNOT_UPDATE_COLUMN`), whatever the column kind.
  A request naming `$feature_flag` therefore still cannot be honored by mutation; that one property needs a refusal, or the heavier rewrite: `INSERT … SELECT` the cleaned rows omitting the typed columns so the shard recomputes them, then lightweight-delete the originals.

The switch also changed two behaviors, measured on the same shape:

- `SELECT *` on the shard now includes the nine typed columns, where `MATERIALIZED` hid them. Nothing in the repo depended on the hidden shape.
- An insert that names a typed column stores the given value even when it contradicts `properties`, where `MATERIALIZED` rejected such inserts.
  Producers must omit the columns; the Kafka path enforces that because `writable_flag_evaluations` does not declare them.

The remaining fix is pointing the events rewrite machinery at this table, with the `$feature_flag` limitation above built into whatever it does here.

`flag_evaluations` stays deliberately absent from `MATERIALIZATION_VALID_TABLES` until that lands: new `materialize()`-minted columns would only widen what the unfixed path silently leaves behind.

#### If a request arrives before the fix lands

Today the refusal costs nothing, because the table is empty.
Once it holds rows, a property removal with `delete_all_events` refuses whenever a single flag-evaluation row carries the named property, and the operator has no way through: `delete_all_events` and `events` are mutually exclusive on the model, so the request cannot be narrowed to exclude `$feature_flag_called`, and the admin Retry button replays the same failure.
The only exits are waiting out the TTL or shipping the fix above. The table partitions by month with `ttl_only_drop_parts = 1`, so a part drops only once its newest row expires: the real wait is up to about 120 days, not the 90-day TTL. `posthog/models/flag_evaluations/sql.py` says the same thing next to the partition clause.

Refusing beats silently under-deleting, so the gate is the right default.
If the fix has not landed by the time real traffic hits, the cheaper stopgaps are letting a request exclude event names so an operator can scope around the table, or recording an explicit, audited acknowledgement on the request so an operator can accept the residue rather than being stuck.
Doing nothing means the first affected GDPR request becomes an escalation.

### Event removal with a HogQL predicate does not reach `flag_evaluations`

`compile_hogql_predicate` resolves against the events HogQL table and emits events-specific physical columns. There is no HogQL table definition for `flag_evaluations`, so the fragment cannot run against it. Requests without a predicate are swept normally; requests with one are refused if the table holds matching rows.

## Producer prerequisite: person_id parity

Every person sweep is keyed on `person_id`, on `flag_evaluations` as on events.
That is only correct because the producer populates `person_id` for every row, exactly as the events ingestion pipeline does: the resolved `Person.uuid`, or a deterministic per-`distinct_id` uuid when no person was resolved.
The shadow-routing producer (`posthog-code/flag-evaluations-shadow-routing`) forks the enriched event downstream of person resolution, so it inherits that value for free.

If a future producer emitted rows before person resolution, leaving `person_id` unset, a person deletion would strand them.
The fix would belong to the producer, not the scanner.
Keeping the fork downstream of person resolution is the contract, tracked on #81002.

## Related, and deliberately unchanged

`_fetch_stats` counts only the events tables. It feeds `AUTO_APPROVE_MAX_EVENTS`, a cost heuristic rather than a completeness claim, so a request auto-approved as small may move somewhat more rows than measured.

`cleanup_old_events_by_partition` stays events-only. It enforces a multi-year retention floor for a named set of teams, and every other personal-data table already expires sooner under its own TTL.

## Adding a table

Register it in `PERSONAL_DATA_TARGETS`, with capability flags reflecting what its schema can actually take and what the sweep code actually implements: `accepts_property_rewrite` needs the rewrite machinery to reach the table, not just assignable columns.
If it is not going to be swept, add it to `TTL_ONLY_TABLES` with the window you are accepting.
If its storage lives on a cluster other than the one the deletion jobs connect to, give it a `cluster_setting` naming that cluster and mark it `optional`; see "Reach" and "Dispatching" above for which sweeps then reach it and which refuse.

`posthog/clickhouse/test/test_deletion_coverage.py` fails on any storage table that declares `person_properties` and appears in neither list, so the decision has to be made rather than skipped.
