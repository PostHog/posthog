# Handoff: personhog merge design session (2026-07-08)

Purpose: let a fresh agent (or the Claude Code web plan session) continue the personhog ingestion-write planning with the context that lives outside the design docs.
Read the three companion docs first; this file only carries what they do not.

## Read these first (in repo root, this branch)

1. `PERSONHOG_INGESTION_REQUIREMENTS.md` - current-state investigation, invariants I1-I12, requirements R1-R7, open decisions D1-D7.
2. `PERSONHOG_MERGE_SERVICE_DESIGN.md` - Design A: fenced saga with a single commit transaction (durable merge state rows, fences restored from the state table, transactional outbox drained by a relay).
3. `PERSONHOG_MERGE_LEADER_DESIGN.md` - Design B: in-leader claim-and-commit (in-memory leased claims, confirm-before-COMMIT, single journal row written inside the commit transaction, leaders drain their own journal).

The two design docs share identical problem statements and acceptance criteria (AC1-AC10) on purpose: every difference between them is a real design difference. Neither references the other.

## Where the work stands

- The user is deciding D1-D3 from the requirements doc, then will update that doc.
- D1 discussion so far: options (a) re-key to distinct_id and (b) route by team_id were rejected ((a) does not solve merges since a person has many distinct ids on different partitions; (b) has unacceptable hot-team skew). The live question is Design A vs Design B, which are two executions of the same core idea: merge runs on the target person's partition owner (the "executor"), source is claimed/fenced via its own owner, one Postgres transaction commits everything.
- Decided along the way (both docs assume these):
  - Merge input is distinct ids; the router resolves both on the persons Postgres **primary** (mapping writes stay synchronous, so primary reads are never stale) and routes by the target person id. Merges do NOT need the uuid partition re-key.
  - Get-or-create DOES need a routing answer: partition key today is the serial person id, which does not exist pre-insert. Companion decision (not yet made): re-key partitioning and changelog to `team_id:person_uuid`, since UUIDv5 of `team:distinct_id` is computable before insert. Cheap now, expensive after GA.
  - D6 (does the leader learn distinct ids): no. A distinct id does not hash to its person's partition, so a leader-side mapping cache would be uninvalidatable. Mapping stays in Postgres.
  - Changelog tombstones + writer delete handling are required regardless of design choice, and are shared with person deletes (R5/AC5.2).

## Key code facts (verified this session)

- Partition = `murmur2("team_id:person_id") % N`, person **DB id** not uuid: `rust/personhog-router/src/backend/leader.rs:90-102`. Changelog key is the identical string (`rust/personhog-leader/src/kafka.rs:12`), so leader partition == Kafka changelog partition; warming tails exactly the owned partitions.
- The leader has NO Postgres write path. Write cycle: local per-key mutex -> diff -> produce to `personhog_updates` (acks=all, awaited) -> update cache (`rust/personhog-leader/src/service.rs:267-283`). Its PG pool is read-only fallback.
- The writer is a blind versioned upsert (`INSERT ... ON CONFLICT ... WHERE EXCLUDED.version > COALESCE(version,-1)`, `rust/personhog-writer/src/pg.rs:64-73`). No delete concept: a deleted row plus one late changelog message = the row is re-inserted. This is the root of the zombie/resurrection hazard both designs shield against (their W4/W5).
- Per-person locks are pod-local (`DashMap<PersonCacheKey, Mutex>`); single-writer-per-partition comes from the etcd four-phase handoff (Freezing -> Draining -> Warming -> Complete) plus the router's per-partition write stash, not from locks.
- Because the writer lags, the leader cache is AHEAD of Postgres. Anything computing merged properties from PG rows silently loses buffered updates. This is why the merge must execute on the target's owner and fetch source state from the source's owner.

## PoC PR #46857 verdict (not written down anywhere else)

`rust/personhog-merger` PoC (Pawel, Feb 2026, still open, stale, mocked deps only):

- It is a resumable saga: 7 persisted states, distributed lock per merge id, and a marking protocol (`set_merging_target` / `set_merging_source`; `get_persons_for_merge` marks source persons so writes are rejected). ~3300 of 5700 lines are a breakpoint/error-injection test harness for interleavings - the most production-worthy part; reuse the testing methodology.
- Its real contribution is the fencing/marking primitive and typed conflicts (no distributed locks -> crossed merges cannot deadlock), NOT the "separate service" placement. Every step is per-entity and routable to that entity's partition owner, so it dodges the naive stale-PG problem.
- Where it conflicts with the requirements doc: it weakens I6 (intermediate saga states are readable; `try_join_all` distinct id moves can partially fail), and its data model (per-property `VersionedProperty`, caller-supplied version, no team_id, no row versions) is incompatible with the ClickHouse contract I2/I3 as written. No cohort/hashkey steps, no guards, only merge case 3, no compensation for the Failed state (markers never unmarked), fences have no TTL (a stuck merge blocks writes indefinitely).
- Both design docs are the negotiated hybrid: keep the fence/claim primitive, typed conflicts, and crash-resumability; collapse the middle saga steps into one PG transaction to preserve I6.

## Compare/contrast axes for Design A vs B (the actual open decision)

1. Durable-before-commit: A persists state rows pre-commit (Started/Fenced, needs GC on abort); B persists nothing until COMMIT (abort = amnesia).
2. Forgotten source lock: A restores fences from the state table on cold load; B relies on the confirm-before-COMMIT round trip plus the W7 timing argument (a full four-phase handoff cannot complete inside the confirm-to-COMMIT gap). W7 is the paragraph a reviewer should attack first.
3. Emission draining: A uses a relay (natural home: writer); B has leaders drain their own journal (post-commit produce, periodic sweep, warming gate).
4. Retry: A resumes a state machine; B checks journal-row existence (committed or never happened).
5. Ops legibility: A's in-flight merges are inspectable in a table; B is smaller with fewer moving parts.

Assessment given in session: B is simpler and easier to reason about because "durable" and "committed" coincide; A degrades more legibly in production incidents. Both are believed correct.

## Suggested next steps

- Pressure-test W7 in Design B (source pod restart between claim and COMMIT) against the real handoff timings in `rust/personhog-leader/src/warming.rs` and the coordination crate.
- Decide A vs B, then fold the outcome into `PERSONHOG_INGESTION_REQUIREMENTS.md` D1/D4 and mark them resolved.
- Decide the uuid partition re-key (gates R1 get-or-create routing, AC1.6) - separate from the merge decision.
- D2 (per-event vs batch update RPCs) and D3 (ClickHouse emission ownership) are still open; both designs' outbox/journal is a partial D3 answer for merge records only.
- Discuss with Pawel: the docs adopt his fencing idea but replace the multi-step saga with one transaction; the PoC's breakpoint test harness should be reused for whichever design wins.

## Suggested skills

- `adding-personhog-rpc` - before writing any proto/RPC for MergePersons, FencePerson/ClaimPerson, or get-or-create.
- `rust-lint` - after any Rust edit (user also has a standing rule: always run cargo fmt + clippy).
- `writing-tests` - before adding tests; note the PoC harness pattern above.
- `django-migrations` - the merge state/journal/outbox tables live in the persons Postgres; check how rust/persons_migrations are managed before writing any.

## Session working agreements (user preferences)

- Never `git push` without explicit user confirmation.
- Avoid em-dashes in all writing.
- Docs use semantic line breaks, no hard wrapping.
