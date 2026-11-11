**What round 1 changed.** Run intake is now solid and `IdempotencyKeys` is struck. Encryption covers all three rest places. The webhook route calls Run intake directly. The two-deploy cutover and the Kafka gating sit inside Run intake, so this page zooms into its parts.

**Premise.**

- **Run intake** (`nodejs/src/cdp/intake/`) owns everything about accepting a run once: the run id, the Postgres claim, the Kafka producer and its consumer, the dead-letter writer, and the lifecycle row.
- **TransactionalEmail** owns what a send means: validation, the replay lookup, refusals and the fingerprint.
- The routes keep only HTTP.
- The cyclotron job queue owns the row: the job codec moves into it, and row encryption lives in the codec.

❓ **Q1** - **Run intake's interface**: A or B?

- **A:** `launch(runs, { wait: 'committed' | 'acked' })`, with an overload per `wait`.
  - `committed` claims in Postgres and returns `created | replayed | mismatch`.
  - `acked` returns `accepted | replayed | mismatch`. Run intake picks shadow or async from the team flag.
- **B:** two calls, `claim(runs)` and `submit(runs)`. The send route picks between them by the team flag.

Both have `recall(run)`, which reads the claim without writing.

➡️ A.

- The cutover is a property of intake, not of the send route. With A, every Kafka step (shadow, async, removing the synchronous insert) changes one module, which is the reason Q3 of round 1 gave for having it.
- The webhook route passes `committed` and gets a type with no `accepted` in it.

---

❓ **Q2** - **The intake consumer inside Run intake**: should the consumer be a part of Run intake on plain `createKafkaConsumer`, not a `CdpConsumerBase` subclass?

- It would take its dependencies explicitly: the queue, `EncryptedFields`, the dead-letter writer and the lifecycle rows.
- It would await the claim inside the batch handler.

➡️ Yes.

- `CdpConsumerBase` builds about 25 services the consumer never uses.
- Consumer v1 stores offsets in a `.finally`, even when the background task rejects. An insert that isn't awaited in the handler can therefore lose a send.
- The consumer and the producer share the message codec, so they belong in one module.

---

❓ **Q3** - **Its own dead-letter writer**: should Run intake write the dead-letter topic with a small writer of its own, rather than reuse `CdpDeadLetterService`?

- It copies the service's header names (`dlq_step`, `dlq_class`, `dlq_topic`/`dlq_partition`/`dlq_offset`, `dlq_timestamp`, `dlq_team_id`).
- `dlq_reason` is a fixed code, never `error.message`.
- The value is the original, still-encrypted bytes.

➡️ Yes.

- `CdpDeadLetterService` is shaped around events and their failure sinks.
- Matching headers keep the replay at the end small: a `cdp-dlq-replay`-style consumer that reads the same headers.

---

❓ **Q4** - **The job codec into cyclotron-v2** (Strong): should `serializeState` and `v2JobToInvocation` move from `job-queue-postgres-v2.ts` into `cyclotron-v2` as a leaf module, with row encryption inside it?

➡️ Yes, in this change.

- Round 1's Q4 already puts row encryption in the codec, so the codec's seam moves anyway.
- Moving it breaks the 4-file import cycle, `cyclotron-v2/index.ts` → `janitor.ts` → `job-queue-postgres-v2.ts`.
- The janitor and the email worker then decrypt through the same module that encrypts.

---

❓ **Q5** - **TransactionalEmail as its own module** (Strong): should the send route's ~195-line closure become `TransactionalEmail.accept(request) → Outcome`, with the route mapping `Outcome` to HTTP?

➡️ Yes, in this change.

- Step 1 of the cutover moves the replay lookup ahead of the refusals, which rewrites the closure anyway.
- Its 7-symbol reach into the lifecycle row chain then goes away. That row belongs to Run intake (Q6).

---

❓ **Q6** - **Run intake owns the run id and the lifecycle row**:

- **The run id:** a run carries `{ scope, key, fingerprint }`, and Run intake derives `runId = uuidv5(team, scope, key)`. The scope is `transactional-email` for sends and the flow id for webhooks.
- **The lifecycle row:** written only after `created`. In async mode the consumer writes it.

➡️ Yes.

- Webhook keys are scoped per flow today and transactional keys per team, and one derivation keeps both.
- #133461's `uuidv5(team:key)` never shipped, so changing it costs nothing.
- Writing the row after `created` removes the "queue the row, then drop it on failure" sequence that sits at 3 sites today.

---

❓ **Q7** - **A keyed fingerprint**: the fingerprint now rests in Postgres and travels in Kafka. Should it become an HMAC-SHA256 keyed from `ENCRYPTION_SALT_KEYS`, compared against every key so a rotation doesn't break the 24h window?

➡️ Yes. Today's fingerprint is an unsalted SHA-256 over `variables`, so a 6-digit login code can be recovered from it by brute force.

---

❓ **Q8** - **Follow-ups, not this change**:

- one cyclotron producer handle per process instead of 3 managers and pools (Worth exploring)
- the webhook handler as a plain module, off `CdpConsumerBase` (Worth exploring)
- one outcome vocabulary shared by TypeScript and Django, which maps on error strings in 4 places (Worth exploring)

Should these stay follow-ups?

➡️ Yes. None of them moves a seam this change moves.
