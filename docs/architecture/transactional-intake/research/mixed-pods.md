# Mixed-pod transactional email idempotency

## Result

The claim “valkey+dual and dual+postgres are safe; only valkey+postgres is unsafe” is false under the requested failure model.

- `valkey+dual` serializes through Valkey only while its 60-second lease holds. A stalled Valkey sender can create a random-ID job after a dual sender has committed the deterministic-ID job.
- `dual+postgres` prevents two job inserts within the Postgres retention epoch, but does not guarantee replay: Valkey pending/unavailable states and new refusal checks can hide an already committed Postgres record.
- Pre-cutover images, including #132891 without #133461, cannot read Postgres-only writes. Rolling back to them after a postgres-mode send can duplicate a completed send immediately.
- No sequence of code-only rolling deploys can make _every_ coexisting pair safe under arbitrary stalls/crashes starting from today's master. Master already has an unfenced expiring lease followed by a non-idempotent insert. A bounded compatibility rollout is possible, described below; its first edges inherit that hazard and cannot honestly be called unconditionally safe.

This is static read-only research, not a runtime reproduction or exhaustive model-checker execution. I inspected the fetched refs with `git show` and three-dot diffs. No checkout files, commits, or remote refs were changed. The checkout already had a modified `rust/common/hogvm/node/Cargo.lock`; I did not touch it.

## Refs and citation convention

- **M**: `origin/master`, `8ddc69966975d9b239df6b473d45ba96c8638326`.
- **I**: `origin/posthog/cyclotron-idempotency-keys`, `b73c1c147000f83e9c5dc83aa4211c132b668674` (#132891).
- **C**: `origin/posthog/transactional-email-idempotency-cutover`, `623a9f685039cbae70dc16197d6ab3468bfaa652` (#133461).

All unqualified file:line references below are on **C**, not the working tree. Abbreviations:

- **API** = `nodejs/src/cdp/cdp-api.ts`.
- **Keys** = `nodejs/src/cdp/services/hogflows/idempotency-keys.ts`.
- **Manager** = `nodejs/src/cdp/services/cyclotron-v2/manager.ts`.
- **Janitor** = `nodejs/src/cdp/services/cyclotron-v2/janitor.ts`.
- **Queue** = `nodejs/src/cdp/services/job-queue/job-queue-postgres-v2.ts`.
- **Email** = `nodejs/src/cdp/services/hogflows/transactional-email.ts`.
- **Webhook** = `nodejs/src/cdp/consumers/cdp-source-webhooks.consumer.ts`.

**L** denotes either M's route or I's route: their route and Keys behavior are unchanged by I (the three-dot diff for those files is empty). **V/D/P** denote C with `valkey`/`dual`/`postgres` respectively. I adds the storage primitive and janitor, but its send route does not call the new primitive.

## Scope of “safe,” “retry,” and “loss”

The primary comparison is the same team, key, and fingerprint within a still-valid retry window, with identical authentication and route validation. A different fingerprint should return 422. An overlapping request before any commit may legitimately receive 409: I distinguish this from a retry refused _after_ a durable queue commit. Refusing a valid replay is an availability/contract failure, not itself proof that an acknowledged job was lost. “Double-send” here means two independently executable Cyclotron jobs for the key, as requested, not proof of two provider deliveries. Worker/provider delivery semantics are outside this API handoff analysis.

A key reused after its entire promised retention window is a new epoch. A second job then is not automatically a deduplication failure. The code nevertheless has inconsistent epoch boundaries between the stores.

There is no demonstrated false 202 with zero durable jobs for a same-payload retry within one epoch in these paths: Valkey queued markers follow a successful queue write, and Postgres commits key+job atomically. Temporary failures can prevent a caller from getting a send queued, and worker checks can skip a queued email, but these are distinct from silent API handoff loss.

## The actual protocols

| Image/mode | First store operation                                                               | ID                | Queue write       | Completion write  |
| ---------- | ----------------------------------------------------------------------------------- | ----------------- | ----------------- | ----------------- |
| L (M or I) | Valkey reserve                                                                      | fresh random UUID | plain insert      | Valkey markQueued |
| V          | Valkey reserve, then PG fingerprint lookup **only if reserve did not return early** | fresh random UUID | plain insert      | Valkey markQueued |
| D          | Valkey reserve                                                                      | UUIDv5(team:key)  | atomic PG key+job | Valkey markQueued |
| P          | Valkey peek                                                                         | UUIDv5(team:key)  | atomic PG key+job | none in Valkey    |

Evidence: API:1349,1362–1407,1425–1461; Email:78–82; `nodejs/src/cdp/services/hogflows/hogflow-executor.service.ts`:92–113 (fresh ID); Queue:165–208,217–236; M API:1360–1420. The configured default is V, `nodejs/src/cdp/config.ts`:384.

All four C paths return on Valkey `replayed`/`in_flight`/`conflict`/`unavailable` **before** any PG replay handling (API:1375–1386). D has no explicit PG read ahead of checks. P's PG replay detection is also its queue insert, **after** `refuseTransactionalEmail` (API:1411–1428). V's PG read is read-before-write, not a claim.

Valkey reserve is atomic `SET EX 60 NX GET` (Keys:185–209). Queued markers live 24h from `markQueued` invocation, not initial reservation (Keys:14–15,232–237). Release and mark ownership compare **invocationId**, not a unique lease token (Keys:20,23). markQueued can recreate an absent key, and silently stops if another invocation owns it (Keys:299–311). D reuses the same invocationId on all attempts, so two different D lease holders are not distinguishable owners.

PG key+job transaction: Manager:350–403. The unique key row serializes same-key claimants; the second statement uses a fresh snapshot to find the winner's fingerprint (Manager:357–399). An existing unexpired key means replay or mismatch, regardless of whether the job was already cleaned up (Manager:419–425). The key is not the job row: migration `rust/cyclotron-node-migrations/20261110000001_add_idempotency_keys.sql`:4–17.

## Pair matrix

“Sequential” below means first request completed, then second starts, with healthy stores, unchanged checks, and both records still valid. “Concurrent” means both requests may pause at any awaited operation. The traces in the next section specify the actual breaking schedules and citations.

| Pair                         | Sequential A→B                    | Sequential B→A                                       | Concurrent / failure verdict                                                                                            | On master already?                                                  |
| ---------------------------- | --------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| V+V                          | replay                            | replay                                               | **double-send** with expired pending lease (T1); **refused-retry** while commit lacks marker (T4); new PG-read 503 (T6) | T1/T4 yes; PG dependency no                                         |
| D+D                          | replay                            | replay                                               | no duplicate within PG epoch; **refused-retry** (T4/T5); lease-owner aliasing (T8)                                      | marker-gap refusal yes; hidden-PG replay/aliasing no                |
| P+P                          | replay through PG                 | replay through PG                                    | no duplicate within PG epoch; **refused-retry** on changed checks or Valkey outage (T5/T6)                              | changed-check replay regression no; store outage refusal existed    |
| V+D                          | V→D replays Valkey                | D→V replays Valkey (or PG if marker absent/expired)  | **double-send** in either ordering across lease expiry (T2); **refused-retry** (T4/T5/T6)                               | lease hazard yes; migration-specific random/deterministic split new |
| D+P                          | D→P replays Valkey                | P→D replays PG only after checks                     | no duplicate within PG epoch; **refused-retry** after commit (T4/T5/T6)                                                 | some Valkey failure forms yes; PG-only checks regression no         |
| V+P                          | V→P replay if V marker visible    | P→V replay by PG read                                | **double-send without expiry/outage**, both initial orderings (T3); **refused-retry** (T4/T5/T6)                        | race is new                                                         |
| L+L (M/I in any combination) | replay                            | replay                                               | **double-send** T1; **refused-retry** T4/T6                                                                             | yes, exactly master                                                 |
| L+V                          | replay                            | replay                                               | **double-send** T1; **refused-retry** T4/T6                                                                             | lease hazard yes; V adds PG-read outage                             |
| L+D                          | L→D replay Valkey                 | D→L replay if marker exists                          | **double-send** T2; also immediate sequential duplicate if D marker never lands (T7)                                    | lease hazard yes; D's durable record invisibility new               |
| L+P                          | L→P replay only if marker visible | **double-send** immediately: P writes no Valkey (T7) | **double-send** T3/T7; **refused-retry** T4/T5/T6                                                                       | PG-only incompatibility new                                         |

Every L row applies separately to M and I. Thus this table covers old+each mode, #132891-only+each mode, M+I, and #132891-only baselines. Installing #132891 changes no send-route safety property until a caller actually uses its new atomic API.

No pair above earns an unconditional “safe” under all requested failures. D+D, D+P, and P+P do earn “safe against duplicate job creation within the retained PG epoch,” assuming all their insertions use that primitive. Ordinary completed same-payload retries with unchanged checks are safe for all C/C pairs, including V+P; its failure is a concurrency race, not an unavoidable sequential mismatch.

## Breaking schedules and proof boundaries

### T1 — legacy/plain writer outlives its lease (V+V, L+L, L+V)

1. A reserves `key→pending(randomA)` (Keys:185–199), and passes or pauses in checks/queue await (API:1411/1432; M API:1389/1404).
2. More than 60 seconds pass (Keys:14). B reserves `key→pending(randomB)` and reads no PG key if it is V (API:1393).
3. B plain-inserts job B (API:1432), then marks B queued (API:1461).
4. A resumes and plain-inserts job A. There is no ownership recheck or fencing at insertion. A's late mark cannot replace B's marker because the IDs differ (Keys:23).

Two jobs exist. Swap A and B for the other ordering; L and V both use fresh random IDs and plain inserts, so all assignments work. A can also have committed before stalling at markQueued; B then duplicates an already-sent job after the pending TTL. This is already master behavior (M API:1366–1371,1404,1420; M Keys:14,23).

### T2 — V/L with D, both orderings

**V/L starts first:** A reserves a random ID; a V A completes PG lookup with no row (API:1393), then stalls beyond 60s before plain insert. D B reserves the now-empty Valkey key, commits deterministic key+job (API:1428; Manager:357–403), marks queued. A resumes and plain-inserts the random job (API:1432). Two jobs.

**D starts first:** D A reserves deterministic ID and stalls before PG commit. After lease expiry V/L B reserves random ID; V B's PG lookup sees no committed row. B plain-inserts and marks queued. D resumes and commits the deterministic job. Two jobs. A D that had already committed also breaks **L** B because L never reads PG; V B instead sees that committed key and replays while its lookup considers it unexpired.

The extra PG read in V protects only the ordering “PG commit before V lookup.” It does not protect “V lookup before PG commit.” This is the precise limit of the claimed bridge. Master's expired-lease concurrency hazard exists, but master has no cross-protocol deterministic job.

### T3 — V/L with P, no TTL expiry needed

**V/L starts first:** A reserves Valkey pending but P B previously performed `peek` and saw absent (API:1377; Keys:220–223). V A looks up PG before B's commit and sees absent (API:1393). Both pass checks. P B commits the deterministic job; V/L A plain-inserts its random job. P never rechecks Valkey.

**P starts first:** P B peeks absent and pauses. V/L A reserves, and V A looks up PG absent. P resumes and commits; V/L A resumes and plain-inserts. The queue completion order can also be reversed. Thus either pod can start first and either job can commit first.

If P's peek runs _after_ A's pending reservation, P returns 409 instead; that particular ordering avoids a duplicate. A read of absent is not a shared atomic exclusion point. API:1375–1407,1411–1432 are the relevant await boundaries. This race is new relative to master.

### T4 — committed job hidden by a pending Valkey marker

A commits its job but pauses/crashes before markQueued. A same-key B reads the still-pending record and returns 409, even though a job is durably queued (API:1375–1382). Applies to any pairing with a V/L/D writer and any reader while the pending record survives; P also honors pending. D may have committed the key and job transaction already, yet neither D nor P checks PG before returning 409.

Reversing the requests simply changes which reserves first; if P is the first writer, it creates no pending marker, but a D retry can reserve a pending marker and stall before discovering P's committed record; another P retry is then refused by that marker. No additional job is created. Master already has the commit→mark gap; hiding an available PG proof is new. A genuine pre-commit 409 is expected contention, not this post-commit failure.

### T5 — valid PG replay reaches current send refusals first

P A commits its job, writing no Valkey record. Sending is then suspended/paused or recipient suppressed. D B reserves absent Valkey, or P B peeks absent; both call `refuseTransactionalEmail` before attempting PG insertion and return 422 (API:1411–1428,1524–1537). Quota produces 429, and inactive workflow produces 400 as additional variants. The PG record would have replayed, but is never consulted. This is sequential and needs no concurrent race.

D A with markQueued lost yields the same failure once pending expires; a D A with a healthy marker hides the defect until that marker disappears. For D+D and P+P choose the corresponding same-mode writers/readers. For V+D/P, a PG writer followed by D/P reader applies; a V reader normally does its PG check before these checks, but its pending marker can still hide replay (T4). L cannot discover a PG-only key at all (T7).

Master with a healthy queued marker replays before those checks (M API:1372–1385); hence the intended replay-after-block behavior regresses in the PG paths. Master with a lost marker can also refuse, but it has no durable PG replay proof to ignore. Earlier schema/auth/team/workflow checks remain ahead of both stores on all images (API:1268–1320); this report does not claim the migration fixes those existing limitations.

### T6 — outage behavior

- Configured Valkey is unreachable: `reserve` returns unavailable (Keys:181–204), and `peek` also returns unavailable (Keys:219–226). **P returns 503 before PG**, even if the exact key+job committed and PG is healthy (API:1385–1386). So “postgres mode removes the Valkey dependency” is false while the host remains configured.
- Valkey pool is **null**, rather than unreachable: reserve returns unavailable, but peek returns **absent** (Keys:181–184 versus 214–217). P proceeds to PG. Removing Valkey config while old pods/records still matter discards the only way P can honor legacy keys; it is not a safe equivalent of tolerating an outage.
- PG fingerprint read fails in V: after acquiring a fresh pending reservation, V returns 503 and best-effort releases the key (API:1393–1399). This occurs even for a new key and even if the queue insert itself would have worked. Existing Valkey `queued` records replay before this read. A failed release leaves a temporary 409 until the pending TTL. Master has no extra PG read and therefore no such read-specific dependency.
- D/P PG transaction failure produces 500 (API:1434–1457,1483–1487), not the explicit 503. Before a known rollback no key/job persists. A COMMIT acknowledgement lost after actual commit is ambiguous: D releases Valkey in its catch, but its PG key remains and prevents another D/P job; V reads that key and replays; L can duplicate it. The comment “Nothing was queued” at API:1452 is not true for an ambiguous commit. Master has the analogous ambiguity for plain inserts, without PG deduplication on retry.

Failures can refuse a valid retry or postpone a new send; they do not by themselves prove a false successful acknowledgment or deletion of an accepted job.

### T7 — rollback to pre-cutover code loses visibility

**P→L:** P queues and returns 202 without writing Valkey. L then reserves absent Valkey and plain-queues a different random ID (M API:1366–1371,1404). Two jobs, even sequentially and immediately with healthy stores. I behaves exactly like M here.

**L→P:** when L has marked queued, P peeks and replays. If L committed but its marker never lands, P first returns 409 until pending expiry; after expiry it sees no PG key and commits a second job. Thus the other ordering is safe only with the Valkey marker intact.

**D→L:** normally replays Valkey. If D's mark never lands, wait for pending expiry and L creates a random job despite D's durable PG key. **L→D** has the same failed-marker duplicate: L's random job has no PG key; D claims one after lease expiry. V avoids the D→V _completed PG commit_ duplicate while its PG key is readable, but not the in-flight races in T2. These mixed-image failures are distinct from saying all current modes are safe after an env sequence.

### T8 — deterministic invocation ID is not a unique Valkey lease owner

D A acquires a lease and stalls beyond 60s. D B acquires the next lease for the same key, with **the same invocationId** (API:1367–1368). A's late `release` can delete B's lease or queued marker (Keys:20); its late `markQueued` can replace B's record (Keys:23). PG still prevents two same-epoch jobs, but Valkey can present false in-flight/conflict state to other pods or erase replay visibility to L.

For differing fingerprints, A can have committed fingerprint F1, while B reserves the expired lease for F2. A's late mark overwrites B's pending F2 with queued F1; B's eventual PG mismatch path releases by the shared deterministic ID and can delete A's queued marker (API:1438–1448). These are not safe ownership checks. Use a random attempt/lease token distinct from stable job identity. Master's fresh random invocation IDs do distinguish these leases.

## TTLs, retention, and janitor

1. Valkey pending is 60 seconds. It is not extended during checks or queueing, and no fence is checked by plain insert. Renewal alone would not prove safety under an unbounded stall.
2. Valkey queued expiry is 24h after `markQueued` starts, including a delayed completion start (Keys:232–237). Background retries preserve that completion's absolute expiry rather than starting a fresh 24h at every retry (Keys:283–305). They are process-local, capped at 10,000 entries, and can be lost on process death (Keys:149,254–265). No guarantee exists that a queued marker eventually lands.
3. PG expiry is `max(now, job.scheduled)+24h` calculated before acquiring the transaction connection (Manager:350–375). It is not refreshed on replay. Ordinary transactional jobs use immediate scheduling. Long acquisition/transaction delays can consume part of this window before commit.
4. PG atomic claim honors an expired key **while its job still exists**: reclamation requires expiry AND absence of that job (Manager:366–367). Janitor applies the same job-existence guard (Janitor:523–548). It is therefore misleading to say PG always forgets at exactly 24h.
5. V's fingerprint read uses only `expires_at > NOW()` (Manager:431–436), unlike PG claim and janitor. Counterexample: D/P key has expired but its job is still running/retained; Valkey marker is absent. V reads PG absent and queues a random job, while D/P would replay the retained key. This affects V+D/P and V after earlier PG history, even in a sequential schedule; it is new relative to master. Whether this is outside the minimum 24h contract does not remove the implementation inconsistency or duplicate executable jobs.
6. Once both stores expire and the job is gone, a second send is permitted key reuse, not a retry guarantee violation. A missing janitor run does not extend expired PG protection when the job is gone: the claim itself reclaims the expired row. With a live job, an expired PG key can return mismatch for a new payload after Valkey would permit reuse.
7. The reverse skew also matters. D commits PG at t0, marks Valkey at t0+delta. Its Valkey marker outlives PG's expiry. Once the job is gone, P/D could reclaim the PG key, but first read the still-queued Valkey record and replay the old send (same payload) or return 422 (new payload). This is refusal of a new epoch / delayed key reuse. V also replays that marker. If the caller expects a fresh send after 24h from initial acceptance, this is apparent loss of that _new_ send, not loss of the original queued job. Master already measures TTL from completion too, but cross-store skew introduces a second definition of expiry.
8. A sufficiently delayed old completion can recreate an absent Valkey record for an old job after other store history has expired (Keys:23,232–237). Without a bounded lifetime/fence, no finite “wait 24h” alone proves all historical legacy state and requests have drained.

For within-window same-payload retries, I found duplicate and refused-retry schedules, but no independent durable-handoff **loss** schedule. Returning an old replay for a newly intended send after retention is the epoch ambiguity above; do not collapse it into loss of an already accepted job.

## Webhook isolation

The webhook uses the same helper and Valkey pool, but a different namespace: API:280–285 versus 324–327; Keys:343–346 incorporates scope, team, and SHA256(key). Webhook additionally prefixes the caller key with workflow ID (Webhook:255–257), whereas transactional PG IDs are team:key (Email:81–82). There is no cross-route key collision or shared PG claim. The cutover env affects the email route only.

Webhook continues to reserve Valkey, use a fresh UUID, plain-queue, and markQueued (Webhook:264,354–363,399–414). On Valkey unavailable it intentionally queues without a reservation (Webhook:376–379); it can duplicate during outages, as well as lease expiry / lost completion, already on master. Changing the shared helper's lease ownership/TTL behavior in a fix would require preserving and checking webhook semantics, but this PR does not migrate webhook writes into the PG idempotency table. Shared infrastructure outages/capacity can affect both routes; key state does not.

## Fixed code-only deployment sequence

### The hard limit

There is **no unconditional sequence meeting the literal requirement from M**, because M+M is already unsafe (T1), and a coexisting M pod can always pause after reserve, outlive its lease, and later issue a random-ID plain insert. No read-only bridge in another pod can fence that old insertion. Code rollback one step back to M reintroduces the same issue. Nor can a program guarantee replay through an unavailable _sole_ store of an old committed record without another durable copy.

If “safe” includes no duplicates under arbitrary pauses starting at the first rolling deploy, the required prerequisite is outside an ordinary app-only rollout: fence all legacy plain inserts at the shared queue/database boundary, or quiesce/drain legacy sends before enabling the new writer. A DB protocol cannot infer a caller's key from an arbitrary old random job row if the old writer never supplied that key. Merely deploying the additive migration in I does not fence old writes. This limitation must be accepted explicitly, not hidden in a claim about adjacent modes.

### Practical reader-before-writer sequence, with explicit limits

The following fixed releases remove the env switch and make adjacent releases compatible **after the legacy lease hazard has been fenced/drained**. The M→R1 and R1→R2 transitions otherwise retain T1/T2 risk; they are compatibility steps, not a proof of stronger semantics than master. Each release is rolled out fully before the next. The schema is additive and retained across rollbacks.

| Release                                     | Reads before any mutable send refusal                                                                                                                                       | Writes for a new keyed send                                                                                                     | Previous-release/rollback contract                                                                                                                                                                                                                 |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R0: additive storage (#132891)              | original Valkey                                                                                                                                                             | original random job + Valkey queued                                                                                             | M and R0 are protocol-identical; no cutover yet                                                                                                                                                                                                    |
| R1: reader bridge                           | authoritative PG replay/mismatch lookup first; then legacy Valkey reserve/classification; recheck PG before returning pending or applying a mutable refusal                 | legacy random plain job + legacy-format Valkey queued; **no new PG-only sends**                                                 | Reads R0's Valkey records, including original random invocation IDs. R0 can still read everything R1 writes. PG lookup must use the same retained-row semantics as atomic claim, not V's expires-only predicate                                    |
| R2: atomic writer with legacy compatibility | PG replay/mismatch first, then legacy Valkey; while legacy writers can exist, participate in their reservation protocol; PG replay is rechecked after awaits before refusal | deterministic key+job atomically; legacy-format Valkey queued marker for old readers; distinct random lease token for ownership | Reads R1's random-ID Valkey results. R1 already reads R2's PG records, so missing markQueued does not hide committed sends on rollback. New writes require atomic claim even after a stale read. Retain the old compatibility path for old records |
| R3: PG writer, legacy reader                | PG authoritative first; legacy Valkey lookup only to honor still-live Valkey-only records; no Valkey reservation for fresh keys                                             | PG key+job only; no Valkey writes                                                                                               | R2 must already be able to read PG-only records _without requiring a Valkey reservation/available Valkey_. R3 reads R2's PG records and all older still-live Valkey records. R2+R3 fresh writers share one atomic PG claim                         |
| R4: PG only                                 | PG retained key/claim only, before mutable refusals                                                                                                                         | PG key+job only                                                                                                                 | R3 already reads PG-only writes; R4 may remove Valkey reads only after no Valkey-only record/request can remain live. One-step rollback to R3 is safe                                                                                              |

R1's PG lookup is not sufficient mutual exclusion with R2: T2 remains until no plain legacy writer can still execute. This table deliberately does not label that edge unconditionally safe. With no legacy writer, R2+R3 and R3+R4 use the same atomic queue protocol, so stale absence reads cannot create two jobs. Rolling back R2 to R1 reactivates plain writers and their inherited stall hazard; **strict** one-step rollback safety therefore requires retaining atomic PG insertion in the rollback-capable floor, or retaining the external fence. Reader compatibility alone does not prove concurrency safety.

In an implementation seeking the strict guarantee, make that floor a repaired common queue primitive used by **all** supported images, including the rollback image, before allowing PG-only writers; do not advertise M or R1 as a safe rollback target after that point. It must carry the stable key and fingerprint to the transaction, not merely make job UUIDs deterministic (job cleanup would erase that protection).

Necessary details for the repaired releases:

- A committed PG result must win over Valkey pending, unavailable, and an obsolete fingerprint marker. Distinguish “legacy key might exist but could not be read” from “fresh PG epoch definitely owns this key.” While Valkey-only historical sends remain possible, blindly ignoring a Valkey outage can duplicate them; failing closed may be necessary, so full availability cannot be promised in that phase.
- A replay lookup must precede current suspension/suppression/quota checks. If a concurrent send may commit while checks await, recheck on a refusal; define the response's linearization point. For fresh sends the atomic transaction must still perform the final create-or-replay decision. An early read alone cannot prevent T3.
- PG key identity must stay stable across every supported release, as must fingerprint normalization. A reader must return the original invocation ID for legacy records rather than fabricating the UUIDv5 ID.
- Valkey attempt ownership must use a unique lease token, separate from the stable invocation ID. This requires an explicit compatible record/script transition if legacy helper users remain; deterministic invocation IDs alone are not valid lease tokens.
- Use one specified retention epoch. PG lookup, atomic claim, and janitor must agree on whether an expired row with a retained job is still authoritative. Define the post-24h behavior rather than letting Valkey delay and PG job retention decide it differently.
- Before R4, measure the wait from the **last possible Valkey-only completion**, not the start of a rollout: fully drain/terminate old in-flight handlers, close rollback to Valkey-only writers, then allow the last legacy replay TTL to elapse. A code-only time delay with arbitrarily stalled old requests is not proof. A rollback that writes new Valkey-only records resets this condition.
- Do not backfill PG keys from a pending Valkey reservation and treat them as queued: that can manufacture a false replay with no job. Legacy queued markers can be honored as compatibility evidence, but their random invocation ID must remain available if persisted elsewhere.

The minimal conceptual stages are **teach readers → change writers atomically while retaining old reads → remove old reads after historical state drains**. More releases are needed if rollback to each preceding writer is supported. An env enum does not encode these compatibility floors, and “move one setting at a time” does not solve image/env races or unfenced legacy inserts.

## Verification limits

This report proves counterexamples by source-level schedules at awaited store/queue/check operations. It does not claim an exhaustive automated enumeration of every JavaScript await. The relevant cross-request state transitions are Valkey reserve/peek/mark/release and PG read/claim/commit; other awaits can extend stalls or change refusal outcomes but supply no additional exclusion. I ran no builds, tests, migrations, or production queries. No production deployment settings were inspected, so configured-host outage and null-pool behavior are kept separate.
