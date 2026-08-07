# Backfilling realtime cohorts

How historical state gets injected into a running streaming pipeline without double counting, and how a cohort becomes safe to serve from.

**Audience:** engineers with no prior context. **Prerequisite:** [realtime-pipeline.md](./realtime-pipeline.md), end to end. This document leans on its condition hashes and leaf state keys (§2.1), the reverse index (§6), the RocksDB column families (§7.3), the eviction sweep (§10.1), register rows (§10.2), and the merge tombstone (§11).

---

## 1. Why backfill exists

The streaming pipeline's state is purely forward-looking. It knows what it has folded, and nothing else. Five situations need state the live stream can never provide:

|     | Trigger                                             | What is missing                                                                                                                                                                                                 |
| --- | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | A team is newly allowlisted                         | All windowed history for every cohort of that team. Membership under-counts for up to the longest window.                                                                                                       |
| T2  | A cohort is created                                 | History inside the window for the new cohort's conditions. The cohort starts empty and fills only as new events arrive.                                                                                         |
| T3  | A cohort is **edited**                              | State under the _new_ leaf state keys. Before the reconcile snapshot existed (§5.8), members under the old definition kept membership forever, because nothing emitted `left` for a leaf that no longer exists. |
| T4  | The store is wiped (disaster recovery, schema bump) | Everything since `now - max(window)`.                                                                                                                                                                           |
| T5  | Dormant persons                                     | Person-property leaf state for people who never emit events, so mixed cohorts under-count them indefinitely.                                                                                                    |

Backfill is three separate jobs stacked together:

1. **Get the history into Stage 1 state** without corrupting what the live path is concurrently building.
2. **Make downstream consistent**, which the pipeline's at-most-once output cannot do on its own (realtime-pipeline.md §13).
3. **Open the serving gate**, and only for the definition that was actually backfilled.

That third job needs a word on what the gate is for. Feature flags can target a cohort, and the flags service evaluates flags without querying ClickHouse, so it needs the cohort's membership available locally. `Cohort.is_flag_compatible` is the check that decides whether a given cohort's membership is trustworthy enough for that path. It requires the cohort to be a realtime cohort, then requires `last_backfill_events_at` if it has behavioral filters and `last_backfill_person_properties_at` if it has person or person-metadata filters. A mixed cohort needs both, and a cohort with neither kind of filter is never compatible even if both stamps are set.

The backfill finalizer is the only writer of those columns, and a cohort edit is the only thing that clears them. Before this machinery existed the gate could never open.

## 2. Why the obvious approaches do not work

**Replay the old events through the processor.** Fails three independent ways.

- _Volume._ For a busy team, a 30-day window holds several orders of magnitude more events than one pod can process in a day, so a replay takes weeks and competes with live traffic throughout.
- _Double counting._ Stage 1 counts are increments, and replay dedup is per source Kafka offset, not per event UUID. There is no UUID dedup anywhere. Any replayed event the live stream also delivered is counted twice, durably, for a full window.
- _Ordering._ Replayed events would interleave with live ones on the same partition, and the window-slide rules would make the result depend on arrival order.

**Recompute the state in SQL and bulk-load it.** Faster, but it means a second implementation of leaf matching. Every divergence between that implementation and the production evaluator (a coercion rule, a timezone edge, a HogVM builtin) becomes silent state corruption, indistinguishable from a real membership difference.

**Import the previous pipeline's membership as a starting point.** It gives no Stage 1 state, so every subsequent event computes membership from a state that never supported it, and it leaves no way to tell whether a later membership difference is a bug in this pipeline or an artifact of the import.

## 3. Day tiles

The chosen unit is a **day tile**: one message saying "on calendar day D, person P matched condition C exactly N times".

```jsonc
{
  "kind": "behavioral_tile",
  "team_id": 42,
  "person_id": "0192-...", // canonical person, resolved at scan time
  "condition_hash": "a1b2c3d4e5f60718",
  "day_idx": 20614, // whole days from the Unix epoch to that day's local midnight
  "count": 3, // ABSOLUTE matched count for that day
  // run bookkeeping and fence fields are added in §5.3 and §6.2
}
```

**It is keyed by `condition_hash`, not by leaf state key.** Matching is a property of the bytecode. Windows, thresholds, and explicit date bounds are applied at state level, per leaf. So one tile fans out through the existing reverse index to every leaf that shares the predicate, and each leaf trims to its own window. One scan serves every cohort that reuses the condition.

**The count is absolute, not a delta**, which is what makes application idempotent (§5.1).

**Tiles go to `cohort_stream_seed_events`**, the fifth co-partitioned 64-partition topic (realtime-pipeline.md §3), keyed the same way as the live topic. A tile therefore lands on the partition that already owns that person's state, and the existing worker applies it. No new state machinery, no second store.

This cuts volume twice. Collapsing events to `(person, condition, day)` triples drops the message count by roughly an order of magnitude before match filtering applies, and each tile then costs one or two store operations with **no HogVM work at all**, because matching already happened in the seeder. Replay's per-event evaluation cost is the part that made it impossible; tiles delete it.

## 4. The moving parts

```text
+---------------------------------------------------------------+
| Django (products/cohorts/backend)                             |
|  detects shape changes, nulls readiness, creates runs,        |
|  checks preconditions; the finalizer CAS-stamps readiness     |
+------------------------+--------------------------------------+
                         | Postgres: cohort_backfill_runs
                         |           cohort_backfill_run_cohorts
                         |           cohort_backfill_chunks
                         v
+---------------------------------------------------------------+
| cohort-seeder (Rust)                                          |
|  orchestrator: discover runs, establish B, plan and claim     |
|                chunks, scan ClickHouse, evaluate, produce     |
|  dispatcher:   send reconcile control messages                |
|  marker watch: tail the marker topic, fold completion bits    |
|  observer:     prove completion, write the run's outcome      |
+------------------------+--------------------------------------+
                         | Kafka: cohort_stream_seed_events (64p)
                         v
+---------------------------------------------------------------+
| cohort-stream-processor                                       |
|  seed follower consumer, apply fence, redirect, fan-out,      |
|  slide, max-merge, Stage 2, emit tagged origin=seed;          |
|  reconcile worker: paged cf_stage2 scan, unconditional        |
|  emission, per-partition completion markers                   |
+------------------------+--------------------------------------+
                         | cohort_membership_changed*  (deltas + snapshot)
                         | cohort_reconcile_markers    (64 per cohort per run)
                         v
                    downstream consumers
```

The seeder shares the processor's evaluation code through the `cohort-core` crate: the HogVM executor, the globals builders, leaf state key derivation, timezone bucketing, and the wire types, all pinned by byte-frozen golden tests. That shared kernel _is_ the fidelity guarantee. A divergence between backfilled and live membership cannot be blamed on a second evaluator, because there is no second evaluator. (The one place this does not reach is the Python parity tooling, which re-implements marker parsing by hand and can drift.)

## 5. The correctness rules

### 5.1 Absolute counts and max-merge

For a daily-bucket leaf the processor applies a tile as `bucket[day] = max(bucket[day], tile.count)`, and a compressed-history leaf does the same on its sparse entry. (`BehavioralSingle` ignores the count entirely: it sets its match bit and maxes a timestamp. A person-property leaf rejects a behavioral tile outright.)

Why max, and not the alternatives:

- **Sum** double-counts every overlap between what the seeder scanned and what the live path consumed. That is the replay failure again.
- **Overwrite** loses live counts when the live path saw more than the scan did, which happens for any event that arrived after the scan.
- **Max** is idempotent, order-insensitive, and, _provided the live-applied events are a subset of what the tile counted_, absorbs the overlap exactly.

Getting that subset relationship to hold is the job of the next three rules.

Idempotency is what makes every failure mode boring. Kafka redelivery, a chunk re-run after a crash, a zombie worker's stragglers arriving late: none can move a bucket to a value no scan justified, because `max` only ever raises it to a count some scan actually observed. The apply path detects the no-op structurally, returning `Unchanged` when the merged leaf state compares equal to what was stored, and an `Unchanged` result never mints a second transition.

### 5.2 Disjoint domains and the boundary `B`

Every run pins a **boundary instant `B`**, and the two domains meet at a day edge rather than trying to dedup individual events:

- **Seed domain:** only full calendar days, in the run's pinned team timezone, **strictly before** `day(B)`.
- **Live domain:** everything the shuffled stream delivers, which for a new cohort or a newly enabled team is coverage from roughly `B` onward.

Django creates the run with `boundary_at = NULL` and status `awaiting_boundary`; the seeder sets it on first discovery with a compare-and-swap (CAS) that also moves the run to `seeding`. The exception is disaster recovery, where the operator supplies the boundary explicitly, because after a store wipe the processor resumes from old committed offsets and "now" would be a lie about where live coverage actually restarts.

Two residual gaps are accepted rather than fixed:

- **The boundary day itself under-counts.** Events on `day(B)` that arrived before `B` are in neither domain. The error decays as that day exits the window.
- **Future-dated events** (client clock skew) with an event day after `day(B)` but an arrival before `B` fall in neither domain. Seeding future days is not an option: a tile for a future day would slide live windows forward and zero live buckets.

Neither gap has a counter today. If you need to know their size, you have to measure it out of band.

### 5.3 `S_chunk`, the arrival bound

Events reach ClickHouse late. An event stamped yesterday can be inserted today. Without an upper bound on _arrival_, a scan would be a function of when it happened to run, and a tile would make a claim it cannot stand behind.

So every claim stamps **`S_chunk`**, and the scan adds `coalesce(inserted_at, _timestamp) < S_chunk`. A chunk's result is then a pure function of `(pinned run row, day, band, S_chunk)`: everything else it depends on is frozen at run creation (§5.7).

`S_chunk` is re-stamped on every claim, so a re-run after a crash uses a _later_ bound and sees strictly more late arrivals. That is safe in exactly one direction, and it is the direction max-merge wants: the re-run's count for a day can only be greater than or equal to the original's, so applying it after the original is a monotone improvement rather than a conflict. A re-run's tiles are never-smaller, not byte-identical.

The bound is deliberately `S_chunk` and not `B`. Events that arrived _between_ `B` and the scan (late arrivals for old days) **are** included in the tile. After the fence, those events have already been counted live, and max-merge absorbs them exactly instead of losing them.

### 5.4 The apply fence

Here is the one genuine double-count branch left.

Suppose the live consumer is lagging, which is exactly the disaster-recovery case where a wiped processor is replaying hours of backlog. A tile computed at `S_chunk` counted an event E whose arrival was before `S_chunk`. The tile is applied first: `bucket = max(0, 3) = 3`. Then the lagging live consumer reaches E and increments: `bucket = 4`. E is now counted twice, durably, for a full window.

The fix is ordering. **A tile may only be applied once live consumption on its partition has passed the tile's scan point.**

The processor keeps a pod-wide map of **live time watermarks**, one per partition: the running maximum broker timestamp over the live events that partition's worker has actually folded. Note that this is a _timestamp_, unrelated to the offset commit floors in realtime-pipeline.md §5. It advances per batch, and strictly **after** the fold and after the offset is marked, so unprocessed events can never open the fence early. A tile is applied only when `watermark > s_chunk_ms + margin` (`COHORT_SEED_FENCE_MARGIN_MS`, default 10 minutes, covering clock skew between the ClickHouse inserter and the shuffler). The comparison is strict; exactly at the bound is still closed.

No watermark at all means the fence is **closed**, the fail-safe direction. Watermarks are forgotten on every partition assignment and revocation, so each tenure starts fail-closed.

An **idle probe** handles the opposite problem: on a partition with no live traffic the watermark would never advance and the fence would never open. A separate task wakes every `COHORT_SEED_WATERMARK_IDLE_PROBE_INTERVAL_MS` (30s, first tick skipped so it cannot race boot recovery), compares the events topic's log-end offset against the highest offset the worker has folded, and for partitions that are genuinely caught up **advances the watermark to wall-clock now**. That is what lets a quiet partition's tiles through.

Until the fence opens, the seed partition's work sits in an in-memory holdover and the partition is **paused** at the broker. Seeding is a work queue; it can wait. (Seeds for partitions this pod does not own are a different case: they are dropped rather than held, which is safe only because their offsets were never dispatched, so Kafka replays them.)

Only day tiles carry a fence. Person seeds, reconcile control messages, and undecodable messages are fence-open, because none of them bounds the arrival of events over the live stream.

### 5.5 Slide before evaluate

Windows are anchored at "now" and slide daily, and the live fold silently drops events for days that have already slid out. A tile for an expired day has to behave identically.

For the two counting variants the apply path therefore **slides the window forward first** and only then merges. If the tile's day now falls below the window start it is dropped **without creating a record and without any Stage 2 evaluation**.

The bug this kills is subtle. An expired tile that _created_ a record would briefly evaluate to "entered", then be swept and emit "left": a membership flap. And it would be re-triggerable on every redelivery, because the sweep deletes the very record that made re-application a no-op. With slide-first, out-of-order and duplicate tile delivery provably converge to one final state.

`BehavioralSingle` has no window array to slide, so it uses the equivalent guard: the tile's synthetic instant is the **end of that day** in the team timezone, and if the resulting eviction deadline has already been reached the tile is dropped rather than resurrecting the record.

### 5.6 The seed path must not participate in `applied_offsets`

The event path's replay dedup is keyed by **bare partition number, with no topic dimension**. If the seed path took part, seed-topic partition 7 and live-topic partition 7 would collide, and the outcome would be one of two disasters: every tile classified as an already-seen replay (the whole backfill silently no-ops while every chunk reports success), or tile offsets overtaking the live high-water mark so that _live events_ get dropped as replays.

So the rule is: `applied_offsets` and `redirect_dedup` are carried through verbatim, read off the prior record and written back unchanged, never consulted for dedup and never advanced. Tile idempotency rests entirely on max-merge plus the structural `Unchanged` check.

### 5.7 Pinning

A run freezes its inputs at creation. Per condition it pins the condition hash, the behavioral value, the window (`time_value` and `time_interval`, plus a derived `window_days`), the operator and threshold, explicit date bounds, the event name, and whether the key was an action. It also freezes the sorted event-name union and the full filters JSON of every participating cohort. A person run pins only the cohort's person condition hashes plus its scan horizon.

The seeder builds a **frozen catalog** from those pinned filters and resolves every condition's window against it. Its reverse index is the same type the live path uses, but populated from the pin, not from the live catalog.

This is what makes a chunk re-run mean the same thing as its first attempt. Without it, a re-run after some other cohort's edit would narrow the event-name union or resolve conditions differently, and "max keeps the larger count" would become luck rather than design.

The seeder reads `posthog_cohort` in exactly one place, and it is not during scanning: the observer compares a run's pinned shape against the cohort's current one when attributing a shortfall (§6.5).

One subtlety: the _day set_ a chunk covers is planned against the boundary day, but the scan re-checks at wall-clock now which conditions are still active for that day. Window anchors only ever move forward, so the scan-time gate admits a superset of every later evaluation's reachable days. A day whose windows have all slid past is a **vacuous** chunk: no query is issued at all.

### 5.8 Why reconcile must emit unconditionally

The pipeline's output is at-most-once: it commits state before the produce is confirmed, so a crash in between can leave `cf_stage2` **correct** while downstream never got the message.

That has a nasty consequence. A "diff state against downstream" reconcile would see nothing wrong, because the state _is_ right, and emit nothing.

So the reconcile snapshot re-emits the current membership of **every scanned row unconditionally**, both `entered` and `left`, and lets downstream converge last-write-wins. That same unconditional snapshot is what deterministically fixes T3: members who no longer qualify under the new definition finally get their `left`.

## 6. A run, end to end

### 6.1 Django creates the run

**Shape hashes.** `Cohort.save()` computes three SHA-256 hashes over the filter JSON: `filters_shape_hash` (all leaves), `behavioral_filters_shape_hash` (behavioral leaves only), and `person_filters_shape_hash`. The behavioral one hashes exactly the fields that feed the Rust leaf state key, kept in deliberate lockstep with it. When a hash changes on save, the matching readiness column is **nulled in the same write**, so the serving gate closes as the definition changes and flags fall back while state is known-stale.

That block is skipped entirely unless the team is in `REALTIME_COHORT_TEAM_ALLOWLIST`, the cohort is a non-static, non-deleted realtime cohort, and the save actually touches `filters`. Two consequences: soft-deleting a realtime cohort leaves its stamps in place, and the whole block is wrapped in a catch-all exception handler that logs and continues, so a failure inside it leaves readiness un-nulled on a changed definition.

**Triggers.** `post_save` receivers fire on create or on a detected shape change. They come in two independently gated halves, and the difference matters:

- **Supersession** (marking an in-flight run's participations dead, because its tiles describe a dead definition) is gated only on the realtime allowlist.
- **Enqueue** is additionally gated on `COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST`, which is fail-closed.

So a team on the realtime allowlist but off the trigger allowlist supersedes its runs on every edit and never enqueues a replacement, silently losing readiness. Keep the trigger allowlist a subset of the realtime one. Note also that the two settings fail in _opposite_ directions when set to an empty string: an empty realtime allowlist means all teams, an empty trigger allowlist means none.

Enqueue goes through a 5-minute Redis debounce whose TTL equals the Celery task's countdown, so the lock releases exactly as the task runs.

Team-wide runs (T1) and disaster recovery (T4) have no automatic trigger. They come from the management command `create_cohort_backfill_run`, which always creates a team-scope run, even when given specific cohort ids.

**Preconditions.** Before a run may start: the person-merge producer must be on (without merge tombstones, a mid-run merge builds durable membership for a dead person that nothing can retract) and the processor's durability gates must be on (without fsync-before-commit, a crash loses applied tiles that are never redelivered, and readiness would stamp over the holes). Person runs add a TTL attestation, a sizing attestation, and a topic-bytes budget.

The booleans are **operator attestations via environment variables**, not live probes; the seeder and processor config are not visible from where Django runs. The budget is different: it runs a live ClickHouse size estimate and sums the estimates of other in-flight person runs.

When an attestation is missing, the signal path **skips**, counted as `missing_attestations`, rather than creating a `blocked` run. That is deliberate: a `blocked` row would hold the cohort's uniqueness slot with nothing to advance it. The management command hard-fails instead.

**Three tables** come out of this:

- `cohort_backfill_runs`: one campaign. Trigger, scope (`team` or `cohort`), kind (`behavioral` or `person_property`), status, the pinned columns, the preconditions, and later the reconcile bookkeeping. Partial unique constraints allow at most one _active_ run per `(cohort, kind)` and one active team-scope run per `(team, kind)`.
- `cohort_backfill_run_cohorts`: one row per participating cohort, freezing its filters and shape hashes, plus its 64-bit reconcile marker bitmap. A single participation can be superseded without killing a whole team run.
- `cohort_backfill_chunks`: the `(run, day, band)` work units. Django only defines the schema; the entire chunk lifecycle lives in the Rust seeder.

Run statuses are `awaiting_boundary`, `blocked`, `seeding`, `reconciling`, and the terminal `completed`, `superseded`, `failed`, `cancelled`. The first four count as active for the uniqueness constraints. `cancelled` is defined but nothing writes it. `blocked` is worth watching: it is active, so it holds the uniqueness slot, and nothing advances it.

### 6.2 The seeder scans and produces

The seeder is a poll loop, every `SEEDER_RUN_POLL_SECS` (15s).

1. **Discover** runs in `awaiting_boundary` or `seeding`, scoped to _both_ the seeder's own team allowlist and the kinds it is configured to handle. That kind filter is what actually hides person runs while `SEEDER_PERSON_SEEDS_ENABLED` is off. If Django enqueues a run for a team the seeder's allowlist excludes, the run is never picked up and nothing reports an error, so keep the allowlists in sync.
2. **Establish the boundary** by CAS, except for disaster recovery, which waits for an operator-supplied instant. A disaster-recovery run created without one waits **forever**, with no status change and no error field.
3. **Build a frozen catalog** from the participations' pinned filters (§5.7).
4. **Plan chunks**: for each condition, which historical days are still inside its window, cross-cut into `(run, day, band)` rows inserted with `ON CONFLICT DO NOTHING`, so planning is idempotent. `band` splits a huge day by a hash of the person id to bound the aggregation's memory (`SEEDER_BANDS_PER_DAY`, default 1). Planning re-runs on every tick while a run is `seeding`, so raising the band count mid-run is safe for correctness but re-scans every already-confirmed day at the new granularity, and newly appearing chunks can bounce a run back out of `reconciling`.
5. **Claim a chunk** with one `FOR UPDATE SKIP LOCKED` statement that picks a retryable chunk (`pending` or `failed`, under the attempt cap) or one whose lease expired. The claim sets `status='scanning'`, **increments `claim_epoch`** as a fencing token, charges an attempt, takes a lease (`SEEDER_CHUNK_LEASE_SECS`, default 900s, renewed by a heartbeat that cancels the worker the moment it is fenced out), and stamps `s_chunk_at = now()`. Ordering is by `(day, band)` and person chunks sit under a far-future sentinel day, which reuses the otherwise-unused `day` column as a priority field; behavioral chunks therefore win _within_ a claim, though the two kinds have independent concurrency budgets. An expired `produced` lease is reclaimable **without** the attempt cap, because its tiles are already in Kafka and only need confirming; an expired `scanning` lease is capped, and a reaper moves chunks whose worker died without failing cleanly to `failed` at the cap. A clean shutdown mid-scan unclaims and refunds the attempt.
6. **Scan ClickHouse**, one streaming query per chunk (values inlined, not bound):

   ```sql
   SELECT e.uuid, e.event, e.properties, e.timestamp, e.distinct_id, e.person_properties, e.elements_chain,
          if(notEmpty(ov.distinct_id), ov.person_id, e.person_id) AS person_id
   FROM events AS e
   LEFT JOIN (
       SELECT distinct_id, argMax(person_id, version) AS person_id
       FROM person_distinct_id_overrides
       WHERE team_id = <team>
       GROUP BY distinct_id
       HAVING argMax(is_deleted, version) = 0
   ) AS ov ON e.distinct_id = ov.distinct_id
   WHERE e.team_id = <team>
     AND e.timestamp >= <day start> AND e.timestamp < <day end>   -- timezone day bounds
     AND e.event IN (<pinned event-name union>)
     AND coalesce(e.inserted_at, e._timestamp) < <S_chunk>        -- arrival bound
   ```

   The `LEFT JOIN` is the canonical-person resolution and it matters: the events table's `person_id` column is stale for merges that happened after the row was written, so tiles have to be keyed by the survivor resolved through the overrides table at scan time. ClickHouse resolves identity and bounds the snapshot; it never evaluates a cohort predicate. No property filtering, no sampling, no matching happens in SQL. The query carries execution-time, external-spill, and set-size guards, and pins the join algorithm to `grace_hash`.

   There is no pagination. The result is one streaming cursor drained inside a `tokio::select!` against shutdown and lease-loss, bounded by the day, the band, and those ClickHouse guards. A banded run adds a `cityHash64(person) % bands = band` predicate on the _resolved_ person.

7. **Evaluate and aggregate.** Each row builds behavioral globals and runs the candidate conditions through `cohort-core`'s evaluator, the same functions Stage 1 calls. Candidates come from the pinned catalog's event-name index. Each match increments an in-memory `(person, condition_hash) -> count` map. At chunk end the map flushes to one tile per entry, sorted, with the count as a `NonZeroU32` so a zero-count tile is unrepresentable on the wire.
8. **Produce, paced.** Every tile waits on a rate limiter (`SEEDER_TILES_PER_SEC`, default 3000, burst of one). When unacknowledged deliveries reach `SEEDER_MAX_INFLIGHT_TILES` (4000, per chunk task) the loop drains acks before continuing. At startup the producer fetches broker metadata and refuses to run unless the seed topic has exactly the configured partition count, and the partitioner is pinned to `murmur2_random`.
9. **Confirm.** `scanning -> produced` (recording the tile count), then await the residual delivery acknowledgments while folding per-partition produce high-water marks, then `produced -> confirmed` with those marks persisted. A chunk is confirmed only when every tile is durably in Kafka. Anything less fails for retry, which is safe because a re-run's counts can only be greater or equal and application is idempotent.

Every one of those transitions is fenced on the chunk's `claim_epoch`, which increments on each claim, so a zombie worker that wakes after its lease expired cannot write anything. (The heartbeat additionally binds the claimant id.)

### 6.3 The processor applies tiles

The seed consumer is **not** an independent subscriber. It is an assignment mirror of the events consumer group, exactly like the merge and cascade followers, so seed partition _p_ always lands on the pod that owns live partition _p_. Without that, tiles would arrive at a pod with no worker for the person. Enabling it without durable restore is a startup warning, because a committed seed offset has to imply a durably applied tile.

For each tile, in order:

1. **Fence check** (§5.4). Within a partition, held work preserves order: from the first fence-closed message onward, everything for that partition is held, so nothing leapfrogs it.
2. **Tombstone redirect.** Resolved through the same resolver the event path uses. A person merged within the partition applies at the survivor. A person merged **across** partitions gets the tile **re-produced to the seed topic re-keyed to the survivor**, incrementing `redirect_hops` (capped at 8; on exhaustion it applies inline at the best-known target rather than dropping). A read failure here is fail-stop, unlike the event path, because a tile mis-applied to a merged-away person is durable state that reconcile cannot retract.
3. **Fan out** through `by_condition_to_lsk` to every leaf referencing the condition.
4. **Check the leaf's window.** A `performed_event` leaf can carry an absolute `explicit_datetime` range, and those bounds live outside the bytecode, so they do not affect the condition hash and the reverse index routes tiles to leaves the range will then reject. The apply path repeats the day-range check the event path does. The counting variants need no equivalent check: an absolute date range on a `performed_event_multiple` leaf resolves to a zero-day window and is dropped from the catalog entirely. Sub-day windows are likewise never seeded, so hourly leaves warm up organically.
5. **Slide, then max-merge**, per state variant (§5.1, §5.5).
6. **Carry the dedup maps through untouched** (§5.6).
7. **Commit in a fixed order**: Stage 1 write, then Stage 2 recompute, then produce the membership changes and cascades, then commit the Stage 2 bits, then schedule evictions, then mark the offset. Any failure holds the offset and replay re-derives everything.

Every emitted change is tagged `origin: "seed"` plus the `run_id`. Those fields are optional and absent on live emissions, so the live wire format is unchanged.

One deliberate detail: a tile that merges to `Unchanged` still writes its single-leaf register rows and still feeds Stage 2. That is what lets a redelivery repair missing register rows after a crash between the Stage 1 and Stage 2 commits.

### 6.4 The reconcile snapshot

Once a run has planned its chunks and every chunk is `confirmed`, the seeder dispatches a reconcile. (A run with zero chunks satisfies "every chunk confirmed" vacuously, so the planned-chunks precondition is what stops an empty run from dispatching.) Automatic dispatch is gated on `SEEDER_RECONCILE_AUTO_DISPATCH_ENABLED` and requires a second attestation, `SEEDER_CONFIRM_REGISTER_BACKFILLED`, which asserts the store has been running register-writing code long enough that a `cf_stage2` scan will see every relevant person. There is also an operator CLI for the same job.

The control message shares the seed topic with day tiles but is **partition-targeted**: one copy produced explicitly to each of the 64 partitions, because key-based routing would reach exactly one, and every partition owns a slice of the cohort's members.

On the processor, an admitted reconcile enters a per-partition FIFO queue and its Kafka offset is **deferred**, held out of the committable floor until the whole job completes, so a crash mid-scan replays the reconcile rather than losing it. A newer reconcile for the same `(team, cohort, kind)` supersedes a queued older one. The queue is in-memory by design: partition teardown forgets the tenure, so an unfinished reconcile replays from the beginning.

A driver ticks each partition every `COHORT_SEED_RECONCILE_TICK_INTERVAL_MS` (2s) and advances a three-phase scan, at most one substantial page (default 256 keys) of work per tick:

1. **Scanning.** Prefix-scan the contiguous `(partition, team, cohort)` range of `cf_stage2` in person order, re-evaluate each person from current leaf state, correct any stale bit, and **emit every row's membership unconditionally** (§5.8), tagged `origin: "reconcile"`. Unlike the tile and person-seed paths, this scan does not resolve merge tombstones, so a person merged away mid-scan is emitted under the stale id.
2. **DrainingDirty.** The paged scan is interleaved with live traffic over many ticks, so live writes mark their rows dirty while a scan is active, and this phase re-scans and re-settles exactly those rows. Without it, a person whose membership changed mid-scan behind the cursor would be snapshotted stale.
3. **MarkerReady.** After a final dirty check, produce a `reconcile_complete` marker and release the deferred offset.

Markers go to their own topic, `cohort_reconcile_markers`, never the membership topic, whose consumers reject any record without `person_id` and `status`. That topic **must exist before a processor with reconcile enabled starts**, or the process fails at boot. Each marker is keyed `"{team}:{cohort}:{run}:{partition}"`, so a cohort produces 64 distinct keys and a compacting topic cannot collapse them and record a complete backfill as short. The marker payload is the one message in this family whose discriminant field is named `type` rather than `kind`.

A **shape-hash guard** re-runs before every page and every phase step: if the reconcile message's pinned hash does not match the live catalog's hash for that cohort, the job is discarded and deliberately emits **no marker**, so the run is visibly incomplete. The type system keeps a person hash from ever being compared against a behavioral one.

### 6.5 Completion and the readiness stamp

The seeder never writes `completed`. Its job is to establish, with proof, that every partition finished.

A dedicated **marker watcher** consumer tails the marker topic from the watermarks captured at dispatch time, folds each marker into a per-cohort 64-bit partition bitmap, and persists both the bitmap and its own resume positions. Folding is a monotone set union, so replay in any order converges. A start position below the log's low watermark surfaces as an explicit truncation error rather than a silent reset, though that outcome is only logged, not written to the run. One operational constraint falls out of this: **the marker topic's partition count must not change while runs are in flight**, because a run's watch covers the partitions that existed at its dispatch. If the persisted watch names a different topic than the one configured, the run is re-dispatched rather than settled.

The **observer** then settles each run. A positive verdict is cheap: if every active participation already has a complete bitmap, mark it done. A negative verdict is harder, because "we have not seen all 64 markers" could just mean "not yet". It requires two proofs before declaring a shortfall:

1. **Liveness.** The processor's seed consumer group has committed strictly past every reconcile offset the dispatch produced, so the control messages were definitely consumed.
2. **Settlement.** The marker watcher has read up to the end watermarks captured at that liveness check, so any marker that exists has definitely been seen.

Only then does it attribute each short cohort by comparing the pinned shape against the cohort's _current_ one, which is the seeder's one live read of `posthog_cohort`. A match is a **retryable shortfall**: an error string is recorded and the participation stays open. A mismatch, a deleted cohort, an absent row, or an indeterminate comparison is a **terminal supersede**. Every observation write is fenced on the run's dispatch epoch and status, so a concurrent re-dispatch cannot land a stale epoch's write.

The seeder's last write per dispatch cycle is `reconcile_observed_at`, always after every participation outcome, so Django never sees an observed run with an undecided participation.

**Django's finalizer** (a Celery beat task, every 2 minutes, gated by `BEHAVIORAL_BACKFILL_FINALIZER_ENABLED`) picks up runs in `reconciling` with `reconcile_observed_at` set, and for each participation with a terminal outcome runs the readiness **compare-and-swap**. It is an ORM update, roughly:

```sql
UPDATE posthog_cohort
   SET last_backfill_events_at = <now>
 WHERE id = <cohort>
   AND <team scoping>
   AND behavioral_filters_shape_hash = <the run's pinned hash>
   AND last_backfill_events_at IS NULL
```

Read that as illustrative rather than literal: the queryset is team-scoped through a manager that rewrites the team predicate to the project's root team, so for an environment team the CAS targets the root team's cohort rows.

The stamp is not just that UPDATE. Around it:

- A participation already marked superseded is refused before the CAS runs at all.
- Zero rows affected has **two** meanings. If the cohort's hash still matches the pin and the stamp is already set, this is an idempotent re-entry and the participation is simply ratified. Otherwise the cohort was edited after the run finished, so the stamp is dropped, the participation is superseded, and the _new_ run created by that edit's own trigger repeats the cycle.
- If the UPDATE succeeds but ratifying the participation loses a race, the stamp is **rolled back** to null. A successful UPDATE alone is not the stamp.

Why any of this matters: without the CAS a stale run could open the gate for a definition it never backfilled. The sharpest case is a window-only edit, which keeps the condition hash byte-identical, so the stale run's tiles still route to the new leaf and partial coverage is indistinguishable from a finished backfill.

The CAS keys on the **kind-specific** shape hash, not the full one, so a person-property-only edit mid-run does not invalidate a valid events backfill. And a run terminalizes as `completed` when at least one participation stamped and `superseded` when none did, but only once no participation is still held: a held participation leaves the run in `reconciling` for a later pass.

After a successful pass the finalizer invalidates the team's behavioral cohort cache and dispatches a flags cache refresh, so the newly opened gate takes effect.

## 7. Person-property seeds

Behavioral tiles cover event-derived state. Mixed cohorts also need person-property leaf state, which is normally written only when a live event carries `person_properties`. Dormant persons never get it, which is T5.

Person seeds are a separate run kind (`person_property`) with a separate readiness column, a separate scan, and a separate wire type:

```jsonc
{
  "kind": "person_property",
  "team_id": 42,
  "person_id": "0192-...",
  "evaluated": ["...", "..."], // what the scan ran: sorted, distinct, non-empty, at most 1024
  "matched": ["..."], // what came back true: a subset of evaluated
  "scanned_at_ms": 1783470000000,
  "run_id": "...",
  "claim_epoch": 1,
  // redirect_hops, like tiles, is added by the processor on a merge re-key
}
```

The `evaluated` / `matched` split is the whole point. A hash in `evaluated` but not in `matched` asserts **false**, which is what lets a seed retract a stale true. A hash the HogVM never answered is left out of `evaluated` entirely rather than asserted false. Those invariants, plus the 1024 cap and a positive `scanned_at_ms`, are enforced in the constructor, and decoding funnels through it so an illegal payload fails to decode rather than half-applying. (Day tiles are different: their decode does _not_ go through the constructor, and is safe only because every tile invariant is expressed in the field types.)

Planning is different from the behavioral path. Chunks are **UUID ranges** over the `person` table rather than days, sized to a target persons-per-chunk (`SEEDER_PERSONS_PER_CHUNK`). A boundary scan streams the team's live person ids in ClickHouse UUID order and keeps every Nth id as a range edge, so planning memory is bounded by the chunk count rather than by the table. That scan is a full-table aggregation, so a cluster-wide advisory lock ensures only one replica runs it per run, it runs off the poll loop, and a failure backs the run off for five minutes.

The scan horizon filters on the person row's `_timestamp`, **not** on activity, so a short horizon silently excludes people who are active but whose person row has not been rewritten recently. The default (`BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS`, 90 days) is too short for most real runs and should be raised deliberately per run. Only the horizon _instant_ Django persists on the run row reaches the query; the horizon-in-days value in the pinned payload is log-only.

Sizing is checked at startup rather than discovered at runtime: persons-per-chunk times concurrency divided by the seed rate must fit inside half the ClickHouse execution budget, leaving the other half as headroom for a slow cluster. Execution is interleaved scan, evaluate, enqueue, never buffered, so memory stays constant across a chunk.

Applying a person seed is not a max-merge, because the state is a point-in-time boolean rather than a count. Instead:

- **Hash filtering first.** Only hashes still in the team's catalog with a person-property variant survive, and `evaluated` and `matched` are filtered **together**. Keeping a hash in `evaluated` that was dropped from `matched` would retract a true the catalog can no longer re-derive.
- **A last-write-wins verdict** decides whether the seed applies at all. The person record keeps one stamp and one catalog fingerprint for the whole person, so the verdict is whole-record. A seed applies when the record is absent or corrupt; when the seed **beats** the record's stamp by a configured margin (`COHORT_SEED_PERSON_LIVE_MARGIN_MS`, default 15 minutes, because the seeder's scan clock and the event clock are different clocks, so a tie is not enough); or when the record was live-evaluated, its catalog fingerprint is stale, **and** the scan is at least as recent as the record, which is what stops an older scan being admitted against a rotated catalog. Otherwise the live record wins.
- **The merge is a set operation.** Transitions come only from the diff between `matched` and the prior set restricted to `evaluated`; the stored set becomes `matched` plus whatever the prior held outside `evaluated`. An empty diff means `Unchanged`, so a record is **never created** for a person who matched nothing, and store growth stays proportional to matchers.
- **The seed zeroes its own fingerprints**, so the record never claims a full-catalog evaluation and the person's next live event does a full re-evaluation.
- **`last_seen_ms` is floored at the scan instant** so a freshly seeded person is not immediately TTL-eligible, and the record's stamp is raised (never lowered) to the scan instant minus the margin.
- **Neither dedup map is touched**, for the same reason as tiles.

Leaf transitions are minted against the person-property leaf state key, which is how person-property leaf state gets created with **no event context at all**. Nothing is scheduled for eviction: person-property membership has no window, so the sweep never owns these leaves.

## 8. Not overloading live ingestion

Backfill shares partition workers, RocksDB, and a Kafka producer with live traffic. Protection is layered, and the layers are independent.

**Producer side.** Tiles and person seeds have separate rate limiters (`SEEDER_TILES_PER_SEC` default 3000, `SEEDER_PERSON_SEEDS_PER_SEC` default 2000), separate in-flight caps, and separate concurrency slots, so a person scan never occupies a behavioral chunk slot. ClickHouse queries carry execution-time and spill guards. By default one replica runs one behavioral chunk plus, when person seeds are on, one person chunk.

**Store side.** Every seed-path and reconcile-path store read runs on the **maintenance I/O lane**, a smaller semaphore pool separate from the event lane, so bulk tile application cannot starve live event reads.

**Consumer side.** Seed partitions are paused at the broker while any of four causes is active:

| Cause           | Meaning                                                                                                                                                                        |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `fence`         | The live time watermark has not cleared `s_chunk + margin` (§5.4).                                                                                                             |
| `channel_full`  | The partition worker's channel or intake budget refused the dispatch. Live events and seeds share that budget.                                                                 |
| `live_lag`      | Live consumption is behind, so seeding yields. Engages at `COHORT_SEED_LIVE_LAG_PAUSE_MS` (default 120s of watermark age), releases at `COHORT_SEED_LIVE_LAG_RESUME_MS` (60s). |
| `disk_pressure` | The store filesystem is above `COHORT_SEED_DISK_PAUSE_PCT`, releasing at `COHORT_SEED_DISK_RESUME_PCT`. Disabled by default.                                                   |

Two design choices in there are worth calling out. The pause target is **computed** from a ledger of active causes rather than mutated, so "resumed while a cause is still active" is unrepresentable. And the engage and release thresholds are constructible only as a strict pair, so a flapping configuration cannot be expressed.

The disk trigger is off by default on purpose: pausing seeds cannot shrink a store that the _live_ path grew, so a threshold set too low would engage and never release. It also fails open, because an absent or expired disk sample can never pause.

**Alerting posture.** Seed-topic lag in the hundreds of millions during a run is _by design_; it is a work queue, not a health signal. Alert on lag **age** and on **pause age**, never on absolute depth. Pause age matters independently: sustained live load can defer seeding indefinitely without any lag alarm firing.

## 9. Failure modes and known gaps

Handled by design:

| Failure                                               | Handling                                                                                                                        |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Seeder crash mid-chunk                                | Lease expires, re-claim bumps `claim_epoch`, re-run against the pinned row; counts can only come back greater or equal          |
| Duplicate tile delivery                               | Max-merge no-op, detected structurally as `Unchanged`                                                                           |
| Zombie seeder writes after a re-claim                 | Every chunk write is epoch-fenced, and its heartbeat cancels the worker on losing the fence                                     |
| Processor crash after apply, before commit            | Seed messages replayed; max-merge no-op, transitions resolved downstream last-write-wins                                        |
| A membership transition is lost (at-most-once output) | The reconcile snapshot emits unconditionally (§5.8)                                                                             |
| Cohort edited during its own run                      | The edit nulls readiness and supersedes the run; the reconcile hash guard blocks a stale snapshot; the CAS blocks a stale stamp |
| Person merged mid-run                                 | The processor re-keys tiles and person seeds to the merge survivor via the tombstone redirect                                   |
| Tile for a day that expired between scan and apply    | Slide-before-evaluate drops it with no record and no Stage 2 (§5.5)                                                             |
| Live consumer lagged past a chunk's scan point        | The apply fence holds tiles until the watermark passes (§5.4)                                                                   |
| Late events arriving after `S_chunk`                  | Bounded under-count on that day's bucket, shrunk by the `S_chunk` bound and decaying with the window                            |
| Seed topic falls behind its retention                 | Alert on lag age and pause age; re-run chunks, which is idempotent                                                              |

Real gaps, in rough order of how likely they are to bite:

- **No catalog consume floor.** A pod that restarts mid-run with a silently stale catalog can leave live-coverage holes the seed never fills, because the seed stops at `B`. The precondition is a stub. In practice: do not restart the processor while a run is active. The damage signal is the `no_referencing_leaves` tile-drop counter.
- **A dead-lettered chunk parks its run forever.** The run stays in `seeding`, holding the cohort's uniqueness slot, and silently refuses every future automatic run for that cohort and kind. There is no distinct dead-letter status either: an exhausted chunk lands in `failed` like any other failure. Detection is the chunk-failure counters.
- **A `blocked` run parks the same way**, from a different entry point, and nothing advances it.
- **A refused automatic run is terminal.** Nothing re-drives "readiness nulled, no active run". A refusal (budget, slot, race) forfeits that cohort's backfill until the next human edit.
- **A disaster-recovery run with no boundary waits forever, silently.** Nothing validates that the operator supplied one.
- **Timezone changes are unguarded, and worse than they look.** Nothing watches `Team.timezone`. A change mid-run can bucket one event into two different days across chunks, but the sharper problem is that the tile wire carries no timezone: `day_idx` is produced in the run's pinned timezone and interpreted at apply time in the _live_ catalog's timezone, so a change re-buckets every in-flight tile and nothing can detect it.
- **A gate-off run must be fully re-produced.** If the processor's person-apply or reconcile gate is off when a message arrives, the message is skipped **and its offset is committed**. There is no replay-from-marker path, so the affected run has to be superseded and recreated.
- **A `person_metadata` leaf makes a cohort permanently unstampable.** Django's gate counts it as a person filter and therefore demands the person stamp, but person runs refuse any cohort carrying one, so no run can ever write it. (The realtime pipeline also excludes such a cohort outright; see realtime-pipeline.md §6.)
- **`claim_epoch` is carried but never read by the processor.** It is not logged, labeled, or checked there; the fencing it names happens in Postgres at claim time.
- **The reconcile queue is not durable.** It is in-memory, so a partition bouncing mid-scan restarts that cohort's snapshot from the beginning. Correct by design, but it costs wall clock.
- **No sub-day seeding.** Hourly leaves are dropped by the apply path and warm up organically.

## 10. Configuration

Django (`posthog/settings/cohorts.py`):

| Setting                                                               | Default | Purpose                                                                                                           |
| --------------------------------------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------- |
| `REALTIME_COHORT_TEAM_ALLOWLIST`                                      | `none`  | gates shape-hash maintenance, readiness nulling, and supersession. **An empty string means all teams.**           |
| `COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST`                              | `none`  | gates automatic run creation on save. Fail-closed: an empty string means no teams. Keep it a subset of the above. |
| `BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED` / `..._DURABILITY_ATTESTED` | `False` | run preconditions                                                                                                 |
| `BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED` / `..._SIZING_ATTESTED`     | `False` | person-run preconditions                                                                                          |
| `BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET`                       | `0`     | admission budget summed over active person runs; 0 counts as missing                                              |
| `BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS`                     | `90`    | person scan horizon (person row recency, not activity)                                                            |
| `BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS`                    | `64`    | refuse a person run pinning more conditions than this                                                             |
| `BEHAVIORAL_BACKFILL_FINALIZER_ENABLED`                               | `False` | the completion and stamping task                                                                                  |
| `BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED`                        | `False` | widens finalizer discovery to the person kind                                                                     |
| `BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS`                     | `500`   | per-pass discovery cap                                                                                            |

Seeder:

| Env var                                                                                    | Default      | Purpose                                                                                                     |
| ------------------------------------------------------------------------------------------ | ------------ | ----------------------------------------------------------------------------------------------------------- |
| `REALTIME_COHORT_TEAM_ALLOWLIST`                                                           | `2`          | run discovery scope. Note the Rust default differs from Django's.                                           |
| `SEEDER_RUN_POLL_SECS`                                                                     | 15           | discovery cadence                                                                                           |
| `SEEDER_MAX_CONCURRENT_CHUNKS` / `SEEDER_PERSON_MAX_CONCURRENT_CHUNKS`                     | 1 / 1        | independent slot budgets                                                                                    |
| `SEEDER_CHUNK_LEASE_SECS` / `SEEDER_MAX_CHUNK_ATTEMPTS`                                    | 900 / 5      | lease and dead-letter policy                                                                                |
| `SEEDER_TILES_PER_SEC` / `SEEDER_PERSON_SEEDS_PER_SEC`                                     | 3000 / 2000  | produce pacing                                                                                              |
| `SEEDER_MAX_INFLIGHT_TILES`                                                                | 4000         | unacknowledged deliveries per chunk task                                                                    |
| `SEEDER_BANDS_PER_DAY`                                                                     | 1            | per-day aggregation split                                                                                   |
| `SEEDER_MAX_LOOKBACK_DAYS`                                                                 | 400          | planning cap                                                                                                |
| `SEEDER_PERSONS_PER_CHUNK`                                                                 | 1000000      | person range chunk size                                                                                     |
| `SEEDER_PERSON_EMIT_NONMATCHERS`                                                           | `true`       | emit empty-`matched` seeds so stale trues get retracted (a person with no prior state still gets no record) |
| `SEEDER_PERSON_SEEDS_ENABLED` / `SEEDER_PERSON_RECONCILE_DISPATCH_ENABLED`                 | `false`      | person path gates                                                                                           |
| `SEEDER_RECONCILE_AUTO_DISPATCH_ENABLED` / `SEEDER_CONFIRM_REGISTER_BACKFILLED`            | `false`      | automatic reconcile dispatch and its attestation                                                            |
| `SEEDER_RECONCILE_OBSERVER_ENABLED`                                                        | `false`      | the marker watcher and observer                                                                             |
| `SEEDER_RECONCILE_MAX_CONCURRENT_DISPATCHES`                                               | 4            | concurrent reconcile dispatches                                                                             |
| `SEEDER_CH_MAX_EXECUTION_TIME_SECS`                                                        | 14400        | ClickHouse scan budget                                                                                      |
| `SEEDER_CH_MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY` / `..._SORT` / `SEEDER_CH_MAX_BYTES_IN_SET` | 2e10 each    | ClickHouse spill and set-size guards                                                                        |
| `SEEDER_CH_JOIN_ALGORITHM`                                                                 | `grace_hash` | join memory behavior for the overrides join                                                                 |

Processor:

| Env var                                                                  | Default          | Purpose                                                                                                |
| ------------------------------------------------------------------------ | ---------------- | ------------------------------------------------------------------------------------------------------ |
| `COHORT_SEED_CONSUMER_ENABLED`                                           | `false`          | the seed follower consumer                                                                             |
| `COHORT_SEED_FENCE_MARGIN_MS`                                            | 600000           | apply-fence safety margin                                                                              |
| `COHORT_SEED_WATERMARK_IDLE_PROBE_INTERVAL_MS`                           | 30000            | opens the fence on quiet partitions                                                                    |
| `COHORT_SEED_RECONCILE_ENABLED`                                          | `false`          | reconcile snapshot (requires the marker topic to exist)                                                |
| `COHORT_SEED_RECONCILE_SCAN_PAGE` / `..._TICK_INTERVAL_MS`               | 256 / 2000       | reconcile scan budget                                                                                  |
| `COHORT_SEED_PERSON_APPLY_ENABLED` / `COHORT_SEED_PERSON_LIVE_MARGIN_MS` | `false` / 900000 | person seed apply                                                                                      |
| `COHORT_SEED_LIVE_LAG_PAUSE_MS` / `..._RESUME_MS`                        | 120000 / 60000   | live-priority pause                                                                                    |
| `COHORT_SEED_DISK_PAUSE_PCT` / `..._RESUME_PCT`                          | 0 (off) / 55     | disk backpressure                                                                                      |
| `COHORT_REGISTER_TRANSFER_ENABLED`                                       | `false`          | carry register rows across a cross-partition merge, which the reconcile scan's completeness depends on |
