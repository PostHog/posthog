**Premise.** The intake is one deep module, **Run intake**, with one call: `launch(runs)` accepts each run once per key and answers `created`, `replayed` or `mismatch`. The send route and the webhook route call only that. Behind it, the cyclotron Postgres claim is the only deduplication. A Kafka adapter carries sends and a synchronous adapter carries webhooks. Valkey leaves through two code deploys, not a three-way switch.

❓ **Q1** - **Scope**: are these the modules in this change?

- **In:**
  - the Django send service (the `202` contract, and later dropping its `409` mapping)
  - the send route and the webhook route
  - `IdempotencyKeys` (retired)
  - the new Run intake, intake topic, intake consumer and dead-letter topic
  - the cyclotron job queue (the atomic claim, and the job row codec if Q4 takes the row)
  - `EncryptedFields`
- **Out:**
  - the email worker and SES feedback
  - `CdpDeadLetterService`, `cdp_events_dlq` and `cdp-dlq-replay` (copied as a pattern, not changed)
  - the janitor beyond #132891's sweep
  - `CdpConsumerBase`

➡️ Yes. Also in: the send route's body cap. Express takes 20 MB, the producer 1 MB, and the cap has to come before auth and validation pass a send that can't be produced.

---

❓ **Q2** - **Cutover as two code deploys**: should #133461's three-way `CDP_TRANSACTIONAL_IDEMPOTENCY_STORE` give way to a fixed sequence of code deploys, with no setting to step through?

1. **Write both, read Postgres first.**
   - Every keyed send claims in Postgres, atomically with its job.
   - It also keeps the Valkey lease and `queued` marker, so a master pod beside it, or a rollback to master, still sees every send.
   - The Postgres lookup runs before the refusals, and uses the claim's own expiry rule.
   - The lease owner is a random attempt token, not the invocation id.
2. **Postgres only.** It ships once step 1 has run everywhere for 24h, so every live key has a Postgres row. It drops Valkey reads and writes. Rolling back to step 1 is safe, because step 1 reads Postgres first.

➡️ Yes.

- **Why it's safe:** step 1 + master is no worse than master + master today, and step 1 + step 2 both end in one atomic claim.
- **The rule it carries:** never roll back two steps once step 2 has shipped. Master can't read rows that exist only in Postgres.
- **The cost:** this cancels #133461's switch and its `dual` mode. #132891 stays as it is.

---

❓ **Q3** - **Run intake as one module** (the bold opportunity): should this change pull the routes' reserve, lifecycle row, enqueue, `markQueued` and `release` sequence into one module, `launch(runs)`?

- It would have a synchronous adapter for webhooks and a Kafka adapter for sends.
- It replaces `IdempotencyKeys`, the id derivation, and the enqueue sequence open-coded at 3 sites across 2 files.

➡️ Yes, in this change.

- Every bug in the pairing check lives in that sequence, and both routes are moving onto the same claim anyway.
- With two adapters, the seam is real.
- The cutover steps in Q2, and the shadow-to-async Kafka steps, then each change one module instead of two routes.

---

❓ **Q4** - **Encryption at all three rest places**: should a send body be encrypted with `EncryptedFields` on the intake topic, on the dead-letter topic and in the cyclotron job row?

- **Topics:** the same encrypted bytes on both topics. Dead-letter headers carry only a fixed error code, never `error.message`.
- **Job row:** `serializeState` encrypts `state`, and `distinct_id` stops falling back to the recipient's address.

➡️ Yes, all three.

- **Cost:** about 0.07 ms per 20 KB body.
- **Why the row too:** the row holds the rendered email and login codes, and the integration-refs flag fails to off.
- **How the row change rolls out:** it follows Q2's reader-first rule. One deploy teaches every reader to decrypt, the next starts encrypting.

---

❓ **Q5** - **Kafka cutover after the idempotency cutover**: should the Kafka steps (shadow, then async, then removing the synchronous insert) start only once step 1 of Q2 runs everywhere, so every writer, synchronous or consumer, claims in Postgres?

➡️ Yes.

- **Why it's safe:** pods and consumers on different Kafka steps then all end in the same atomic claim, so no Kafka step pair can send twice.
- **What async costs:** a retry that arrives while its first message is still in Kafka gets a second `202`, and the consumer records it `replayed`. A changed body is caught only by the consumer and recorded `failed`. That's #132733's open question on best-effort `422`s.
