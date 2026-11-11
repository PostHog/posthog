**What round 2 changed.** Run intake's interface is `recall(run)` plus `launch(runs, { wait })`. The consumer is a plain module inside Run intake, with its own dead-letter writer. The codec move and the `TransactionalEmail` extraction land as their own refactor PRs. This round draws the four paths through those modules.

**Premise.** Every path ends in one atomic claim, and a request only ever waits on that claim or on the broker ack. The route answers `202` on the ack. The consumer is the authority on `created`, `replayed` and `mismatch`, and it never stores an offset until its claim, its dead letters and its lifecycle rows are durable.

❓ **Q1** - **The ack deadline**: should the route wait for the broker ack up to a fixed deadline, with the producer's `message.timeout.ms` set to the same value?

- A `503 intake_unavailable` then means the message will never land later. The one exception is an ack lost after the write, and idempotency covers that case for keyed sends.
- The value goes to the grilling ticket. Today the only bound is librdkafka's 300s default.

➡️ Yes.

- Without this, a late delivery after a `503` gets a keyed send recorded as `replayed` on retry, which is fine. A keyless send, though, would go out twice, and the caller was told it failed.
- With matching timeouts, a keyless send behaves as it does today when an insert times out.

---

❓ **Q2** - **The consumer's batch order**: should every batch run in this order?

1. Decode and decrypt each message, and dead-letter the ones that can't be decoded.
2. Dedupe by `runId`. The first message wins, and the rest are counted as `replayed`.
3. One `createJobsIdempotently` call.
4. Lifecycle rows: `running` for `created`, and `failed` with `idempotency_key_reused` for `mismatch`.
5. Await all of the above, then store offsets.

➡️ Yes.

- A `mismatch` is a caller error that a replay can't fix, so it becomes a `failed` row, not a dead letter.
- `createJobsIdempotently` throws for the whole call on duplicate ids or one invalid entry, so steps 1 and 2 must come before step 3.

---

❓ **Q3** - **What "can never insert" means**: should only these go to the dead-letter topic?

- no key decrypts the message
- the body isn't JSON
- the message fails the run schema

And these not?

- Postgres errors: retry them.
- A deleted team or a disabled flow: insert anyway, and the worker refuses at send time as it does today.
- A send past its send-by deadline: a `failed` row (#132733's PR 7).

➡️ Yes.

- The dead-letter topic is then only for messages a fix-and-replay can rescue.
- Everything that is the caller's problem ends as a `failed` row they can see.

---

❓ **Q4** - **A circuit breaker on dead letters**: should the writer copy `CdpDeadLetterService`'s breaker? When 3 or more messages, and more than 10% of a batch, would be dead-lettered, it throws instead. The partition stalls and the lag alert fires.

➡️ Yes.

- The case it catches is a bad deploy, such as a pod missing an `ENCRYPTION_SALT_KEYS` entry. Without the breaker, that pod would dead-letter every send it reads.
- Stalling keeps the sends in the topic, where fixing the deploy recovers them with no replay.

---

❓ **Q5** - **A Postgres outage in the consumer**: should the consumer retry the claim in-process with backoff for a bounded time before it throws, never storing offsets meanwhile?

➡️ Yes.

- A throw stops the process, and every restart costs a rebalance across the group.
- One background task per consumer already blocks the next batch, so in-process retries hold the partition without reading ahead.
- The lag alert covers a long outage.

---

❓ **Q6** - **Step 1 when Valkey is down**: during cutover step 1, should a route still answer `503` when Valkey is unavailable, as today?

➡️ Yes.

- During step 1's rollout a master pod can hold a lease that only Valkey knows about. Claiming in Postgres anyway could send twice beside it.
- Step 2 removes Valkey, and with it this `503`.
- A `503` is a retry, not a drop.

---

❓ **Q7** - **The webhook route on the same two steps**: should the webhook route take both cutover steps through Run intake's `committed` path? Its fingerprint would stay the flow id, so a webhook key still never mismatches.

➡️ Yes.

- Master's webhook keys live only in Valkey too, so the webhook route has the same mixed-pod hazard as the send route.
- Keeping the flow id as the fingerprint leaves webhook callers' behaviour unchanged: a repeat answers `200 duplicate`.
