# Personhog ingestion write path: current-state investigation and requirements

Status: draft for review, 2026-07-06.
Scope: what the Node.js ingestion pipeline does with person data today, what the personhog cluster supports today, the gap between the two, and draft acceptance criteria for the new personhog capabilities (merge, delete, distinct id resolution, creation, personless) needed before ingestion can drop its direct persons DB connection.

---

## 1. Where things stand today

### 1.1 Personhog cluster (rust/personhog-\*)

| Service      | Role                                                                                                                                                                                                                                                                                                                                                                                   | Person write surface today                                                                                                                             |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| router       | Stateless entry point. Currently a byte-level gRPC proxy (`rust/personhog-router/src/proxy.rs`), not the typed router the READMEs describe. Routes `UpdatePersonProperties` (and `GetPerson` with `x-read-consistency: strong`) to the leader, everything else to the replica.                                                                                                         | n/a                                                                                                                                                    |
| replica      | Postgres-backed reads (replica pool) plus, as an explicit stopgap, person deletes, `SplitPerson`, and version-floor writes against the primary pool (`proto/personhog/service/v1/service.proto:67-85` carries WARNING comments that these belong on the leader eventually). Also owns all non-person-table writes: groups, group type mappings, cohort membership, hash key overrides. | DeletePersons, DeletePersonsBatchForTeam, DeletePersonlessDistinctIdsBatchForTeam, SplitPerson, SetPersonVersionFloor, SetPersonDistinctIdVersionFloor |
| leader       | Stateful person write service. Partitioned by `murmur2("team_id:person_id") % num_partitions` (`rust/personhog-router/src/backend/leader.rs:88-102`). In-memory authoritative cache per partition, per-(team, person) async mutex, diff-only updates, produces new person state to Kafka `personhog_updates` before mutating the cache.                                                | UpdatePersonProperties only, and it returns NOT_FOUND if the person does not exist (`rust/personhog-leader/src/service.rs:74-77`). No creation path.   |
| writer       | Kafka -> Postgres sink for `personhog_updates`. Idempotent upsert guarded by `WHERE EXCLUDED.version > COALESCE(version, -1)`.                                                                                                                                                                                                                                                         | n/a (closes the leader durability loop)                                                                                                                |
| coordination | etcd-based: coordinator singleton assigns partitions to leader pods, four-phase handoff (Freezing -> Draining -> Warming -> Complete) enforces single-writer-per-partition.                                                                                                                                                                                                            | n/a                                                                                                                                                    |

Clients: Python (`posthog/personhog_client/`) and a full Node.js connectrpc client (`nodejs/src/common/personhog/client.ts`) already exist, with rollout gating helpers.

**No RPC exists anywhere for: person creation, person merge, distinct id claiming/association, personless distinct id insert/read, or `is_identified` transitions.**

### 1.2 The seam in ingestion

Both ingestion servers already wire a `PersonHogPersonRepository` (`nodejs/src/common/personhog/personhog-person-repository.ts`) behind `PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE` / `PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS`:

- Reads (`fetchPerson`, `fetchPersonsByDistinctIds`, `fetchPersonsByPersonIds`, `fetchDistinctIdsForPersons`) go to personhog gRPC for rolled-out teams, with Postgres fallback on error, and always Postgres when `useReadReplica === false` (i.e. `fetchForUpdate` paths).
- **All writes delegate directly to Postgres** (`personhog-person-repository.ts:156-215`).

So the migration surface is well defined: every write method on `PersonRepository` needs a personhog equivalent, plus the merge/transaction paths that bypass the repository interface today.

### 1.3 Related paths already off the ORM (Django side)

- Person API property updates re-enter ingestion as `$set` events via `capture_internal` (no direct DB write).
- Person deletes go through the personhog `DeletePersons` RPC (`posthog/models/person/util.py:510-522`); ClickHouse tombstones are emitted by Django with `version + 100`.
- Person splits go through the personhog `SplitPerson` RPC with `version + 101`.
- The Postgres override tables (`posthog_personoverride`, `posthog_pendingpersonoverride`, `posthog_flatpersonoverride`, `posthog_personoverridemapping`) are **dead** (marked NOT USED since PR #23616). The live override mechanism is entirely ClickHouse-side (see 2.7).
- `rust/ingestion-consumer` never touches persons; it only groups events by `token:distinct_id` so one worker sees all events for a distinct id.

---

## 2. Current-state behavior reference (what personhog must replicate)

### 2.1 Pipeline shape and ordering

- Events are grouped by `token:distinct_id` and processed **sequentially per group, concurrently across groups** (`nodejs/src/ingestion/pipelines/analytics/joined-ingestion-pipeline.ts:261-273`). The Rust ingestion-consumer upstream keeps a distinct id pinned to one worker.
- BeforeBatch: bind a per-batch view of the persons store. Batch: prefetch persons (fire and forget), batch-insert personless distinct ids, then per-event person processing. AfterBatch: flush buffered person updates in one batch UPDATE and produce the resulting Kafka messages as side effects.
- The critical structural fact: **creation and addDistinctId are synchronous inline DB writes; ordinary property updates are write-behind**, buffered in a per-worker cache (`BatchWritingPersonsStore`) and flushed once per Kafka batch. Postgres write and Kafka emission are never in one transaction.

### 2.2 Distinct id resolution

- `fetchForChecking` (replica pool, cached) vs `fetchForUpdate` (primary pool, cached), with in-flight promise dedup and refcounted per-batch cache eviction (`nodejs/src/ingestion/common/persons/batch-writing-person-store.ts`).
- SQL: `posthog_person` joined to `posthog_persondistinctid` on `(team_id, distinct_id)`.
- Batch prefetch does one UNNEST join per batch against the primary.

### 2.3 Person creation

- Deterministic UUIDv5 of `"${teamId}:${distinctId}"` (`nodejs/src/ingestion/common/persons/person-uuid.ts`). This makes recreation and personless upgrades idempotent.
- Single CTE inserts the person row (version 0) and all distinct id rows (version 0 unless personless history forces 1) in one statement (`postgres-person-repository.ts:509-535`).
- Unique-constraint violation -> `CreationConflict` -> fetch the winner by each distinct id and continue (lost race is fine).
- Kafka person + distinct id messages are produced **inline** right after the insert (not deferred to flush).
- Properties over the DB check constraint (`check_properties_size`, ~640KB) reject creation with a `person_properties_size_violation` ingestion warning (non-retriable).

### 2.4 Property updates

- Diff computed against known person state (`person-update.ts:46-135`): `$set_once` only fills absent keys, `$set` only writes changed values (all-or-nothing per event once any key triggers), `$unset` only removes present keys. `$exception` / `$$heatmap` never update persons. `$identify` / `$create_alias` / `$merge_dangerously` / `$set` events force an update.
- Churn filtering: most `$geoip_*` / `$initial_geoip_*` keys do not trigger a write on their own (`FILTERED_PERSON_UPDATE_PROPERTIES`, with `$geoip_country_name` / `$geoip_city_name` exceptions). `PERSON_PROPERTIES_UPDATE_ALL` disables filtering. The leader PoC currently **omits this filtering** (`rust/personhog-leader/src/person_update.rs:22-23`).
- Non-property mutations carried on the same update: `is_identified` false -> true flips, `last_seen_at` bumped to hour precision when the team enables it, `created_at` min-merge during buffering.
- Flush modes: `NO_ASSERT` batch UNNEST update with `version = COALESCE(version,0) + 1` (default), per-person fallback, or `ASSERT_VERSION` optimistic CAS with fetch-merge-retry. Person deleted/merged mid-batch -> `NoRowsUpdatedError` -> re-resolve person id and retry.
- Oversized update: if the stored row is already at the limit, properties are **trimmed** to ~512KB (only trimmable keys) and retried; otherwise rejected with a warning.

### 2.5 Personless mode ($process_person_profile=false)

- Personless events get a fake person: deterministic UUID, `created_at = 1970-01-01T00:00:05Z` sentinel, empty properties. No person row is written.
- `posthog_personlessdistinctid` rows are batch-inserted (UNNEST, `ON CONFLICT (team_id, distinct_id) DO UPDATE ... RETURNING is_merged`) so a later identify knows those events existed; a 100k-entry 4h LRU in the worker suppresses repeat inserts.
- `is_merged = true` is flipped by the merge path (`addPersonlessDistinctIdForMerge`), and personless events for a merged distinct id re-fetch the real person to attach to.
- force_upgrade: if a real person exists for a personless event and the event is >1 minute past person creation, the event is processed personful.
- `$identify` / `$create_alias` / `$merge_dangerously` / `$groupidentify` with `$process_person_profile=false` are dropped with a warning.

### 2.6 Merges

Entry points (`person-merge-service.ts:103-162`):

- `$identify`: merge `$anon_distinct_id` -> event `distinct_id`.
- `$create_alias` / `$merge_dangerously`: merge `alias` -> event `distinct_id`.

Guards:

- Illegal distinct id lists (case-insensitive: anonymous, guest, id, email, undefined, true, false, ...; case-sensitive: `[object Object]`, NaN, None, null, 0; plus quoted variants; plus empty/whitespace). Warning `cannot_merge_with_illegal_distinct_id`, merge skipped.
- `$identify` / `$create_alias` refuse to merge away a **source** person with `is_identified = true` (`$merge_dangerously` bypasses). Warning `cannot_merge_already_identified`.
- Self-merge is a no-op. A failed merge is swallowed (event continues with plain property update).

Four cases in `mergeDistinctIds`:

1. One person exists: claim the other distinct id via `addPersonlessDistinctIdForMerge` (fresh insert -> distinct id version 0; already-personless -> version 1, which materializes a ClickHouse override), then `addDistinctId`.
2. Both map to the same person: no-op.
3. Both exist and differ: full `mergePeople`.
4. Neither exists: create one person with both distinct ids, choosing the previously-personless id as the primary UUID source where possible.

`mergePeople` semantics:

- Survivor row: the **target** (event `distinct_id`) person row survives; `created_at` becomes the min of both; properties merge with **target winning conflicts**, then the event's own $set/$set_once apply on top; `is_identified` forced true.
- Version: `max(target.version, source.version) + 1` (so a later split/undelete deterministically wins in ClickHouse).
- Transaction contents, in order: update survivor (see caveat), move distinct ids (`UPDATE ... SET person_id = target, version = version + 1`, `FOR UPDATE SKIP LOCKED ORDER BY id` when limited), rewrite `posthog_cohortpeople.person_id` and delete+reinsert `posthog_featureflaghashkeyoverride` under the target in one CTE, delete the source person row.
- **Caveat: with the production batch store, the survivor's property/version update is NOT in the transaction.** It is buffered in memory and flushed later. The real atomic unit is {move distinct ids, cohort/flag-override rewrite, source delete}. A crash after commit but before flush loses the survivor's property bump until the next event.
- Retry machinery: FK violation on source delete (concurrent merge added a distinct id) -> refresh + retry up to 5; target gone -> refresh; exhausted -> `PersonMergeRaceConditionError`, event falls back to normal property processing. Merge modes: SYNC unlimited (prod default), LIMIT (-> DLQ), ASYNC (-> redirect topic).
- Kafka on merge: survivor person update, one distinct id message per moved row (version-bumped), source person tombstone (`is_deleted: 1`), all produced after commit. Optional `person_merge_events` topic (default off) feeds the Rust cohort-stream-processor.
- Known hazard: crash between commit and produce loses the ClickHouse messages; there is no reconciliation other than the next version bump.

### 2.7 ClickHouse override model (why distinct id versions matter)

The `clickhouse_person_distinct_id` topic feeds two MVs: `person_distinct_id2` (current mapping) and `person_distinct_id_overrides`, which filters **`WHERE version > 0`** (`posthog/models/person/sql.py:427-452`). Only version-bumped rows (merges, personless claims with history) become overrides. The Dagster `squash_person_overrides` job snapshots the override table, rewrites `events.person_id`, and deletes squashed overrides. Any personhog implementation that changes distinct id version semantics breaks override materialization and squash.

### 2.8 Version fudge constants (cross-language contract)

- Delete tombstone: `version + 100` (Django `posthog/models/person/util.py`, Node `db/utils.ts:144`).
- Split: `version + 101` (outranks delete; Rust `SPLIT_VERSION_OFFSET` in personhog-replica).
- Reset deleted distinct id: `existing + 100`.
- Version-floor RPCs exist in personhog to keep ClickHouse from ignoring lower versions after these fudges.

---

## 3. Invariants the new services must preserve

- I1. Person UUID is deterministic UUIDv5 of `team_id:distinct_id` of the primary distinct id. Creation is idempotent under replay and races.
- I2. Person `version` increases monotonically per row; ClickHouse resolves by version (ReplacingMergeTree), so at-least-once Kafka delivery is safe as long as versions are correct. Merge survivor version = `max(both) + 1`; delete = `+100`; split = `+101`.
- I3. Distinct id rows are created at version 0 and only version-bumped when the mapping changes (merge/move) or the id has personless history; `version > 0` is the ClickHouse override trigger. Never emit a version-bumped distinct id message for an unchanged mapping.
- I4. Merge direction: both ids end up on the person that the event's `distinct_id` resolved to; oldest `created_at` survives; target properties win conflicts; survivor `is_identified = true`.
- I5. Merge guards: illegal distinct id lists, is_identified protection for `$identify`/`$create_alias`, self-merge no-op, failed merge degrades to plain property update (never drops the event, except LIMIT/ASYNC modes).
- I6. Atomic unit of a merge in Postgres is at least {move distinct ids, cohortpeople rewrite, hash key override rewrite, source person delete}. (Personhog may strengthen this to include the survivor update; it must not weaken it.)
- I7. `$set_once` fills only absent keys; `$set` writes only changes; `$unset` removes only present keys; `$exception`/`$$heatmap` never touch persons; geoip churn filtering per `FILTERED_PERSON_UPDATE_PROPERTIES` (unless `PERSON_PROPERTIES_UPDATE_ALL`).
- I8. Property size: reject or trim at the current constraint thresholds, with the same ingestion warnings (`person_properties_size_violation`, trim-to-512KB behavior on already-oversized rows).
- I9. Events for one distinct id are processed in order (upstream guarantees grouping; personhog must not reorder writes for one person; the leader's per-(team, person) mutex covers this).
- I10. Personless distinct id claims are idempotent upserts returning `is_merged`; merge flips `is_merged = true`.
- I11. Every person-state change eventually produces a ClickHouse-bound message (person, distinct id, tombstone) carrying the post-write version. Today this can be lost on crash-between-commit-and-produce; the new design should be no worse, and ideally better (see D3).
- I12. Deleted persons can be recreated by in-flight events (accepted race, mitigated by the +100 tombstone); personhog must not make this worse (e.g. by resurrecting from a stale cache after a delete).

---

## 4. Gap analysis

| Capability ingestion needs                                     | Personhog today                                                                                                                                                    | Needed                                                               |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| Resolve distinct id -> person (checking/eventual)              | Yes (replica reads, already rolled out behind %)                                                                                                                   | Nothing new                                                          |
| Resolve for update (strong read)                               | GetPerson strong-read exists on leader, but by person id only, and Node repo currently forces Postgres for `useReadReplica=false`                                  | Strong read by distinct id, routed correctly                         |
| Create person with distinct ids                                | **Missing**                                                                                                                                                        | New RPC (leader)                                                     |
| Get-or-create by distinct id                                   | **Missing**                                                                                                                                                        | New RPC or composed client behavior                                  |
| Property update on existing person                             | Yes (leader), but no creation-on-miss, no `is_identified`/`last_seen_at`/`created_at` mutation, no churn filtering, no size trim/reject parity, single-person only | Extend leader update                                                 |
| Add distinct id to person                                      | **Missing**                                                                                                                                                        | Part of merge/claim surface                                          |
| Personless distinct id claim (insert returning is_merged)      | Only batch delete exists                                                                                                                                           | New RPC                                                              |
| Merge (all four cases, guards, cohort/flag rewrite, tombstone) | **Missing entirely**                                                                                                                                               | New RPC(s) (leader)                                                  |
| Person delete                                                  | Replica stopgap (primary pool), no ClickHouse emission (Django emits)                                                                                              | Move to leader path per proto WARNINGs; decide CH emission ownership |
| Split / version floors                                         | Replica stopgap                                                                                                                                                    | Same as above                                                        |
| ClickHouse person/distinct-id topic emission                   | None (leader emits internal `personhog_updates` only; writer sinks to PG)                                                                                          | Decide ownership (D3)                                                |
| Batch property flush (write-behind)                            | Leader is per-request                                                                                                                                              | Decide: per-event RPCs vs batch RPC (D2)                             |

---

## 5. Draft requirements and acceptance criteria

Numbered R1-R7. Acceptance criteria are written to be testable against the invariants in section 3.

### R1. Distinct id resolution and get-or-create

Personhog must let ingestion resolve an event's distinct id to a person, creating the person if absent, without a direct DB connection.

Acceptance criteria:

- AC1.1 A `GetOrCreatePersonByDistinctId` (name TBD) RPC accepts team_id, distinct_id, optional extra distinct ids, initial $set/$set_once, created_at, is_identified, and a creator event uuid; it returns the person plus a `created` flag.
- AC1.2 Creation uses UUIDv5 of `team_id:primary_distinct_id` (I1). Two concurrent calls for the same distinct id return the same person; exactly one reports `created = true`.
- AC1.3 Concurrent creation via two _different_ distinct ids that lose a race resolve via conflict-fetch, matching today's `CreationConflict` behavior (no error surfaced to the caller when a winner exists).
- AC1.4 Person row and all distinct id rows are inserted atomically, versions per I3.
- AC1.5 Oversized initial properties are rejected with a typed error the client maps to the `person_properties_size_violation` warning path (I8).
- AC1.6 Routing: the router can route this RPC before a person id exists (partitioning input must be derivable from team_id + distinct_id; see D1).
- AC1.7 Strong read-by-distinct-id exists so the `fetchForUpdate` path can leave Postgres.

### R2. Property update parity on the leader

Extend `UpdatePersonProperties` (or add a sibling RPC) to full parity with the Node update path.

Acceptance criteria:

- AC2.1 Supports `is_identified` false->true flips, `last_seen_at` (hour-truncated, team-gated flag passed by caller), and `created_at` min-merge alongside property diffs.
- AC2.2 Implements churn filtering equivalent to `FILTERED_PERSON_UPDATE_PROPERTIES`, with an update-all override, and force-update semantics for `$identify`/`$create_alias`/`$merge_dangerously`/`$set` events (I7). The filter list lives in one place with a cross-language conformance test against the Node list until Node stops computing diffs.
- AC2.3 Size handling parity: trim-and-retry when the stored row is already oversized, reject otherwise, surfacing which happened (I8).
- AC2.4 A batch variant (or documented per-event cost budget) exists such that ingestion's per-Kafka-batch write amplification does not exceed today's batched UNNEST update path (see D2). Target: no more than one Postgres round trip per changed person per flush interval, which the leader's Kafka+writer design already satisfies; the requirement is on gRPC call overhead and leader throughput.
- AC2.5 Returns NOT_FOUND only when the person genuinely does not exist under strong consistency; callers can distinguish "deleted/merged away" to trigger re-resolution (today's `NoRowsUpdatedError` retry loop).

### R3. Personless distinct ids

Acceptance criteria:

- AC3.1 A batch `ClaimPersonlessDistinctIds` RPC upserts `(team_id, distinct_id)` rows and returns `is_merged` per row, idempotently (I10).
- AC3.2 A `ClaimForMerge` operation (standalone or inside the merge RPC) sets `is_merged = true` and reports whether the row was freshly inserted (drives distinct id version 0 vs 1, I3).
- AC3.3 Client-side LRU suppression remains valid: repeated claims are cheap no-ops server-side regardless.

### R4. Merge

The big one. A `MergePersons` (name TBD) RPC that owns the entire merge, server-side.

Acceptance criteria:

- AC4.1 Input: team_id, target distinct id (event distinct_id), source distinct id (alias/$anon_distinct_id), event type ($identify vs $create_alias vs $merge_dangerously), the event's own $set/$set_once, timestamp, event uuid.
- AC4.2 Implements all four resolution cases from 2.6 (one exists, same person, both exist, neither exists) with identical outcomes, including the personless-history version rules and primary-UUID selection in the neither-exists case.
- AC4.3 Enforces the guards of I5 server-side, returning typed outcomes (merged, skipped-illegal-id, skipped-already-identified, race-degraded) so the client can emit today's ingestion warnings verbatim.
- AC4.4 Survivor semantics per I4, version per I2.
- AC4.5 Postgres atomicity at least per I6, including the cohortpeople rewrite and hash key override delete+reinsert. Stretch: include the survivor property/version update in the same transaction (strictly better than today; document the choice).
- AC4.6 Concurrency: concurrent merges touching the same persons converge without deadlock (deterministic lock ordering) and without lost distinct ids; the FK-violation-on-source-delete retry behavior is preserved or made unnecessary by design.
- AC4.7 Emits (or returns for emission, per D3) the survivor update, per-moved-distinct-id messages with bumped versions, and the source tombstone, such that the ClickHouse override MV (`version > 0`) materializes overrides exactly as today (I3, 2.7).
- AC4.8 Cross-partition problem is explicitly solved: source and target persons generally hash to different leader partitions (see D1). The design document must state where merge executes and how single-writer-per-partition is preserved for both persons' cache entries (including invalidating/killing the source person's cache entry on its partition).
- AC4.9 Merge modes: supports an enforced move limit returning a typed limit-exceeded error so the client can DLQ/redirect per today's LIMIT/ASYNC modes.
- AC4.10 A merge that fails mid-retry leaves state no worse than today's (documented partial states), and the client can fall back to plain property update processing.

### R5. Deletes, splits, version floors move off the replica stopgap

Acceptance criteria:

- AC5.1 `DeletePersons`, `SplitPerson`, and version-floor RPCs execute on the write-owning path (leader or a path that invalidates leader cache) instead of the replica's primary pool, resolving the WARNING comments in `service.proto:67-85`.
- AC5.2 A delete invalidates the leader's cached person so a subsequent `UpdatePersonProperties`/get-or-create cannot resurrect stale properties (I12); recreation after delete yields a fresh person at version 0 whose ClickHouse row is still outranked by the +100 tombstone until reset.
- AC5.3 Version fudges (+100 delete, +101 split) remain byte-compatible with the Django/ClickHouse contract (2.8).

### R6. ClickHouse/Kafka emission ownership (decision required, see D3)

Acceptance criteria (once D3 is decided):

- AC6.1 Every person mutation results in exactly one logical ClickHouse-bound message stream with post-write versions (I11), whichever component produces it.
- AC6.2 The produce-after-commit loss window is documented and no larger than today's; if personhog owns emission, prefer a changelog-driven design (writer or leader emitting from the durable `personhog_updates` log) that closes the window.

### R7. Client, rollout, and parity verification

Acceptance criteria:

- AC7.1 The Node `PersonHogPersonRepository` (and a store-level equivalent for merge/transaction paths that bypass the repository) can route each write capability independently behind per-capability rollout flags, with Postgres fallback during rollout.
- AC7.2 Dual-write or shadow-mode comparison exists for at least merges and creates before cutover (compare resulting Postgres rows and emitted versions), given merge complexity.
- AC7.3 Ingestion warnings, DLQ/redirect behavior, and metrics (version disparity counters, merge failure counters) survive the migration unchanged from the operator's point of view.
- AC7.4 End state: ingestion workers run with no `PERSONS_DATABASE_URL` write pool; `PostgresPersonRepository` is only a fallback implementation behind flags, then deleted.

---

## 6. Architectural decisions to make first (open questions)

- **D1. Partitioning vs distinct-id-keyed operations.** The leader partitions by `(team_id, person_id)`, but get-or-create and merge are keyed by distinct id, and a merge spans two persons that generally live on different partitions. Options: (a) re-key leader partitioning to `(team_id, distinct_id)` ownership, (b) route by team_id (hot-team risk), (c) execute merges on the target person's partition with an explicit cross-partition invalidation protocol for the source, (d) run merges through a separate serialized merge service that bypasses the per-person cache and invalidates both entries. This decision shapes every RPC above; recommend deciding before writing proto.
- **D2. Write-behind batching.** Today ingestion batches property updates per Kafka batch (one UNNEST update per flush). Moving to per-event `UpdatePersonProperties` calls trades Postgres write amplification (which the leader's Kafka/writer design already absorbs) for gRPC call volume and leader lock traffic. Decide: per-event RPCs (simplest, leader diffing absorbs no-ops) vs a batch RPC mirroring today's flush. Measure against prod event->changed-person ratios.
- **D3. Who emits `clickhouse_person` / `clickhouse_person_distinct_id`.** Options: (a) client keeps emitting (personhog returns the messages/versions to produce, closest to today, keeps the loss window), (b) leader emits directly after `personhog_updates`, (c) writer (or a sibling consumer of `personhog_updates`) emits, making the durable changelog the source of truth and closing the crash window. (c) is architecturally cleanest but requires `personhog_updates` to carry distinct id and tombstone records, not just person property state.
- **D4. Merge atomicity target.** Today the survivor update is outside the merge transaction (2.6 caveat). Personhog can fix this cheaply since it owns the whole operation. Decide whether AC4.5's stretch goal is required, and what the ClickHouse emission ordering is relative to the transaction.
- **D5. Cohort membership on merge.** The Postgres rewrite exists, but there is a standing TODO that ClickHouse cohort data is not updated on merge. Decide whether personhog's merge should also emit something for cohorts (or explicitly declare it out of scope, matching today).
- **D6. Does the leader learn distinct ids?** The leader cache currently holds person rows only. Get-or-create, addDistinctId, and merge all mutate the distinct id mapping. Decide whether the leader caches the distinct-id-to-person mapping (and how invalidation works across partitions) or always resolves via Postgres/replica.
- **D7. Personless table ownership.** Personless claims are high-volume upserts with no per-person affinity. They may belong on the replica primary-pool path (like other non-cached tables) rather than the leader. Cheap decision, but should be explicit.

## 7. Suggested sequencing

1. Decide D1-D3 (they gate proto design).
2. R3 (personless claims) and R1 (get-or-create): smallest surface, unlocks shadow-testing creation semantics.
3. R2 (property update parity), since the leader path already exists and Node can start shadow-routing simple updates.
4. R4 (merge), largest and gated on D1/D4.
5. R5 (move deletes/splits off the stopgap) plus R6 emission ownership.
6. R7 rollout to zero direct DB writes.
