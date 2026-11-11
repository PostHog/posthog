**What round 4 changed.** Webhooks launch `acked` on their own topic. Every Kafka run claims a row, keyless ones included. Recall runs after the trigger template. Messages may be 2 MB. Webhooks lose the `409`. Run intake's `Run` now carries a `kind`, and keyless runs claim on their own id. This round writes each locked seam as code.

**Premise.** Callers only need to know three things: `recall` reads, `launch` writes, and `IntakeUnavailableError` means retry. The rest stays behind the seams: the flag step, Kafka, encryption, dead letters and the claim's retention rule.

❓ **Q1** - **Fingerprints under every key**: should `createJobsIdempotently` take `fingerprints: string[]` (current key first), store the first, and treat a stored value matching any entry as a replay? This amends #132891 before it merges.

➡️ Yes.

- With one HMAC string, rotating `ENCRYPTION_SALT_KEYS` turns every retry inside the 24h window into a `mismatch`.
- #132891 isn't merged yet, so the change is one parameter and one `= ANY`.
- Its migration comment ("sha256 of the request") gets corrected in the same edit.

---

❓ **Q2** - **The message envelope**: should the Kafka value be a single Fernet token over the JSON `IntakeMessage`?

- Plaintext headers carry only `intake_version`, `team_id`, `run_kind` and `run_id`.
- The key is `runId`.

➡️ Yes.

- Routing and metrics need nothing from the body, so nothing secret goes in a header.
- `EncryptedFields` already tries every key on decrypt, so the token needs no key id.

---

❓ **Q3** - **Topics and retention**:

- `cdp_intake_transactional_email` and `cdp_intake_workflow_webhook`: 18h retention.
- One `cdp_intake_dlq`, keyed by its `dlq_topic` header: 7 days.

Are these the names and retention periods?

➡️ Yes.

- Intake retention has to stay under the 24h claim window, or a very late redelivery could insert twice.
- 18h leaves room for the lag alert, which fires long before.
- Seven days on the dead-letter topic outlasts a weekend.
- A replay is safe at any age: a dead-lettered run was never claimed, and the send-by deadline still fails stale sends.

---

❓ **Q4** - **Encrypt every v2 job's state**: should the codec encrypt the state of every cyclotron v2 job, rather than only transactional and webhook runs?

- It rolls out reader first: deploy A decodes both formats, then deploy B encodes encrypted.

➡️ Yes.

- One rule has no kind check to get wrong, and every hog flow can hold an email body.
- The cost is about 0.3 ms per 100 KB, next to an insert that takes milliseconds.
- Never roll back past deploy A once B has shipped.

---

❓ **Q5** - **The send route's outcomes**:

- `accepted`/`replayed` → `202`
- `mismatch` → `422`
- `refused` → today's 4xx
- `invalid` → `400`
- `too_large` → `413`
- `unavailable` → `503 intake_unavailable`

`409 idempotency_key_in_flight` and `503 idempotency_unavailable` go after step 2. Is this the full HTTP contract?

➡️ Yes.

- Django already maps `202` and `413`, and treats any unknown error code as `DeliveryUnavailable`.
- Its only change is deleting the `409` mapping once step 2 ships.

---

❓ **Q6** - **The team intake flag**: should one multivariate flag, `cdp-intake-kafka` (`shadow` | `async`, evaluated per team), drive the Kafka steps for both routes? It would be read synchronously with a 60s cache, like the integration-refs rollout, and fail to off.

➡️ Yes.

- Off is the synchronous claim, which stays correct while the flag service is down.
- The last Kafka step deletes both the flag and the off path, so it never fails to a path that's gone.

---

❓ **Q7** - **ADRs**: should three of the locked seams get an ADR?

1. The two-deploy idempotency cutover instead of a store switch.
2. Webhooks on Kafka with a synchronous trigger template.
3. A claim row for every Kafka run, keyless ones included.

Encryption of all job state gets a line in the capture doc instead.

➡️ Yes.

- Each of the three is surprising without context, hard to reverse, and chosen over a real alternative.
- Job-state encryption is easy to reverse: one deploy back to plaintext.
