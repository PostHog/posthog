# personhog / Postgres parity

`PersonhogPersonsStore` runs in shadow behind `BatchWritingPersonsStore`. While it does, the two are expected to write the same person rows for the same events, and a difference in **either** direction is a finding: being better than the Postgres backend still spends the shadow signal, because an operator comparing rows cannot tell an improvement from a bug.

This file records where the two deliberately part, so a row diff can be read without re-deriving each case.

## Recorded divergences

Each is intentional. Each is a place where a row comparison will show a difference that is not a defect.

### `last_seen_at` on a merge fold

The leader max-merges the destroyed source's `last_seen_at` into the survivor. Postgres keeps the target's own, because it never passes the field to its merge update.

The two part only where a source was seen _after_ the merge event, which needs out-of-order events or clock skew above the hour floor. personhog's answer is the truer one: the survivor is both people, and the source row is destroyed, so its timestamp has no other copy.

The ordinary (non-merge) update path does **not** diverge. Both backends max-merge there — the leader through `person.last_seen_at.max(requested)`, Postgres through `computeOpsScalarUpdates`, which writes the field only when the candidate is later.

### An unseen target id against an identified source

Where the merge target's distinct id is unseen and the source is already identified, Postgres attaches the new id onto the identified person. Its `mergeAllowed` guard sits only on the both-ids-resolve path, so the one-exists branch calls `addDistinctId` with no `is_identified` check.

personhog refuses, and births the target on its own, because otherwise any identify request could alias its unresolved target onto a known identified person. The backends therefore disagree on how many persons exist, not merely on a field. With both persons live they agree exactly.

### The unit of loss on a properties size violation

Postgres flushes with one `UPDATE … FROM UNNEST` statement, so one oversized row aborts it and every person in that batch is dropped without retry.

personhog drops only the rejected segment and writes the remainder. This is a deliberate break: reproducing a whole-batch loss to match a backend we are replacing is not worth doing. Reachable only when a lane splits into two segments, which needs a key left in the `pair` state (`$set_once` plus `$unset`) meeting a later `$set_once` on that key.

### Pre-epoch `created_at`

Any timestamp at or below zero diverges, and on two paths. On the merge path, `person-merge-service.ts` clamps a pre-epoch timestamp to 0, Postgres writes that as 1970, and the Rust reads 0 as an absent proto3 `int64` and substitutes the current time. On the create path there is no clamp at all: the store sends the raw milliseconds, identity treats anything at or below zero as "now", and Postgres writes the actual pre-epoch date. Reaching either needs a bad client clock; the divergence is the same family — the layers disagree about what a non-positive timestamp means.

### Person `version` at birth and after a fold

A Postgres-born person starts at version 0 with its creation properties in the insert. A personhog-born person with creation properties ends at 1: the stub inserts 0 and the leader's property write bumps it. After a merge, the fold's version is `max(emitted floor, max sealed) + 1`, which can exceed Postgres's `max(target, source) + 1`. Shadow deliberately does not compare versions, so this costs nothing there; it is an observable row difference at cutover.

### What the merge warnings carry

The saga result names persons by row id, and only for a merged source, so warnings emitted from personhog merges carry `otherPersonId: undefined` where Postgres fills the source's uuid, and a saga refusal that returns no survivor leaves `personId` empty too. On the flush path, Postgres emits a `person_properties_size_violation` ingestion warning per dropped person, while personhog relies on the leader's own warning, throttled to one per team per hour, plus a log line. One more corner: a saga op resumed after a crash cannot know whether it birthed its survivor, so it reports no birth — the newborn misses its `$creator_event_uuid` and the caller runs a follow-up update it may not have needed.

### The move limit, and what happens to an event that hits it

The saga enforces a per-merge distinct-id move limit in every mode. The Postgres backend's SYNC mode does not: its moves are unbounded. A person with more distinct ids than the limit therefore merges on Postgres and comes back `skipped_move_limit` on personhog, where `PersonEventProcessor` routes the event to the DLQ rather than dropping it or failing the batch into a redelivery loop.

This is a difference in what happens to the event, not only in what is stored, and it is the one divergence that costs an event its place in the stream. It is invisible while Postgres is authoritative, because the DLQ decision is made from the authoritative result. It becomes live at cutover.

Folded traffic reaches the same decision by a different route: a fold whose source settles on the limit — or on a lifecycle conflict — aborts and falls back to sequential merges, matching Postgres's all-or-nothing fold, so each event still receives its own verdict rather than being acked on a fold that skipped it.

### Filtered-only ops: dropped here, accidentally retained there

A lane whose every op filtered as no-change is discarded at flush, except on a destroyed-marked person, where no-change against the dead document proves nothing and the lane writes so the tombstone redirect can carry it to the survivor (taking the redirect's plain-write precedence). The rescue needs a local mark, which two shapes lack: a merge verdict reporting no source person id, and a person destroyed by another pod whose verdict never reaches this one. Postgres suppresses the same write but keeps the filtered values in its cached entry, so under overlapping batches a later real change writes them to the row and the shadow comparison flags `properties`; that retention is an accident of the cache's lifetime, not a rule worth matching.

### The conflict-retry budget under contention

A `skipped_conflict` is retried under salted op ids, and the saga records each salted attempt's verdict durably, so the caller's outer retry loop replays the recorded verdicts instead of re-running against fresh state. The effective window for a lifecycle op to release the person is the inner salted loop's backoff, a few hundred milliseconds; Postgres's outer retries genuinely re-run, so its window is the whole retry schedule. A person held longer than the inner window costs the merge on personhog where Postgres may still complete it. The drop is warned and acked, the same terminal both backends use for a lost claim race; under heavy lifecycle contention the personhog drop rate reads higher.

### Recorded ops pin leader fence capacity while parked

A parked op's fences are exempt from the leader's fence-map capacity at rebuild and release only when the op resumes. A pathological parked population therefore consumes capacity until every new fence sheds `RESOURCE_EXHAUSTED` and merge sagas stall at seal fleet-wide — designed backpressure, surfaced by the `personhog_lifecycle_ops_parked` gauge, whose alert should be read with this failure mode in mind.

### A retry racing op garbage collection re-executes

A retry that finds its recorded op just as the retention GC deletes it re-creates and re-drives the op from the frozen request. The re-drive converges — sources already merged resolve to the target and fall out, destroying nothing — but the caller can receive a different verdict than the one originally recorded. Needs a retry arriving more than the retention window late while racing the GC by moments.

### A fold that landed without its step, refused on the re-drive

A fold can commit at the leader and the driver die before the step advance records it. The re-drive re-runs the fold; met instead by a definitive refusal — the mark verification failing, the lifecycle database gone — the op aborts, and the abort has no way to know the fold landed. The target keeps the sources' folded properties while the recorded verdict says nothing merged; the sources and their distinct ids are intact, so this is divergence, not loss — Postgres's transactional fold cannot leave it, and a shadow properties diff on such a target is this shape, not a store defect. Reachable only through a driver crash inside the fold step followed by a definitive refusal on resume.

### A crash-replayed merge and the seal its lane missed

A merge that sealed its sources and crashed resumes from the recorded op on redelivery, so ops folded after the crash miss the sealed snapshot and reach the survivor through the tombstone redirect after the fold, where Postgres would have read them before folding. A shared key can settle differently (the redirect's plain write overrides the fold's target-wins choice) — divergence, not loss, since one real customer value wins either way.

### A reused op id refuses forever where Postgres merges again

The saga records ops by an id derived from the team, the event uuid, the source list, and the move limit — the target is not in the derivation, but it is in the recorded request the replay guard compares. Two merge events sharing one client-supplied uuid but naming different targets therefore collide: the second is refused `op_id_reused` on every delivery until the recorded op ages out of retention, and the store settles it as a lost merge with a `merge_settled_failure` warning. Postgres consults no op id and simply executes the second merge. Invisible under shadow, where refusals never reach a caller; at cutover it is a person-graph difference for clients that duplicate event uuids. The refusal being terminal rather than batch-failing is deliberate — the alternative wedged the partition for the retention window.

### What a shadow flush failure sheds

A shadow release abandons the batch, discarding unwritten segments only that batch was keeping (`personhog_store_shadow_shed_segments_total` counts them). Every later shadow read of an affected person diverges until new writes overwrite the shed keys; correlate the divergence counters with the shed counter before reading such a spike as a store defect. The retention this bounds was the one shadow fault that could take the authoritative process down. Related: identity-service degradation stalls the authoritative pipeline for up to the merge deadline times its retries per merge event, since the shadow leg is awaited by design; a sustained outage is the signal to switch shadow off, not a store defect.

### An extra distinct id created blind resolves on first touch

A creation's extra distinct ids are not memoized — the service can leave a live conflicting extra mapped to its existing person, so the store cannot trust an edge it never saw resolved. A prefetch response for such an id issued before the create and delivered after can briefly record it absent; a null resolution serves both read classes, so an update fetch sees the absence too and takes the create path, which heals it the same way the checking class's next resolve does. Postgres's cache memoizes extras on creation and does not have the window; the divergence is a transient absent answer, never a wrong person.

### Verdicts Postgres has and the saga does not

`skipped_race`, `failed_source_not_found`, `failed_target_not_found`, and `failed_source_has_distinct_ids` come only from the Postgres merge. Three of them fail the batch, so the event redelivers. The saga's vocabulary has no equivalent, so the same physical situations arrive as `error`, which is a settled verdict: the caller acks the event and records the merge as lost.

Same situation, opposite durability decision. Also invisible under shadow, and also live at cutover.

## Shared-path decisions

These are not backend divergences: they change behavior for both backends, including a deployment running Postgres alone, and were made for personhog reasons. Recorded so a pg-mode difference from the old code reads as a decision rather than an accident.

- **Fold runs split at 250 sources.** The saga refuses a request above its batch cap, and refusal spends the whole fold, so the shared planner cuts a longer run into several plans. On Postgres this turns one fold transaction into several for a run that size — intermediate merged states become visible and the target takes a version bump per chunk — which converges to the same result and only occurs on runs that were previously one very large transaction.
- **Merge participants are gated on `isDistinctIdUnmergeable`, not just the illegal-id list.** Ids carrying a NUL or over 400 code points now refuse with the illegal-id warning where the old code attempted the merge and died at the column. Applies to both backends by construction.
- **Source-precedence parity is a standing requirement.** A merge drains the affected lanes under its own fence before the saga runs, so buffered source properties fold into the survivor with source precedence, exactly as Postgres's cache-mediated merge reads them. This single requirement underwrites the store's pre-merge write machinery — the own-fence threading, the fence-holder-never-waits rule, and the deferral accounting. Dropping the requirement would delete that machinery at the cost of redirected ops landing after the fold instead of inside it; it is kept deliberately.

## Decided non-gaps

`properties_last_updated_at` and `properties_last_operation` are left at `'{}'` on personhog-born persons where Postgres writes per-key values. This is recorded rather than fixed. Nothing in the repo reads the values, shadow mode does not diff them, and they are write-only in both backends — set at creation and never updated. Matching them would not make them useful. The only visible effect is the `person_json_field_size_bytes` histogram drifting down, which is operator-visible only.

## Known unexercised

personhog mode produces neither `person_merge_events` nor the ClickHouse `person` and `person_distinct_id` rows; the leader's changelog closes the loop back to Postgres rather than onward to ClickHouse. Both are invisible under shadow, where Postgres still produces them.

## How parity is verified

By running both backends against the same traffic in shadow mode, where `RoutingPersonsStore` compares their answers as they come back.

Reads compare presence, uuid, the identified flag, and properties. Merges compare the survivor and each source's verdict. A difference increments `personhog_store_shadow_divergence_total{verb,field}`, against a denominator of `personhog_store_shadow_compared_total{verb}` so the rate is readable rather than the absolute. Row ids are deliberately not compared: the two backends allocate from independent sequences, so those differ by design, while the uuid is derived the same way on both sides and is what downstream data is keyed by.

Two things this does not cover. Writes are not compared — `createPerson`, `applyEventOps`, and the diff update run on both sides but only the authoritative answer is inspected — so a write divergence surfaces only on the next read of that person. And a comparison that throws is counted separately (`personhog_store_shadow_compare_failed_total`) rather than against the backend, because a fault in the comparison is not evidence about personhog.

There is no in-repo cross-backend _test_, and a Node-side one is not the gap it appears to be. The merge lives in Rust, so a Jest test cannot run it and has to stand a hand-written model in its place. That makes the personhog half of every comparison a model of the thing under test: where the model agrees with the service the test is redundant, and where it drifts the test manufactures a divergence. The in-process comparison has no such problem, because both halves are the real backends.

The pieces that _can_ be tested in Node are, and are: `personhog-persons-store.test.ts` covers the store through its real interface, and the Rust merge semantics are covered in `personhog-identity`'s own tests.
