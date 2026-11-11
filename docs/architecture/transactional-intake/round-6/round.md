**Gut check: yes, the encryption is over-engineered.**

- **PostHog's line.** `EncryptedFields` protects credentials: secret inputs, integration tokens and push tokens. Those are every caller in `nodejs/src/cdp`. Message content isn't encrypted anywhere.
- **Kafka already carries this data.** The cyclotron Kafka job queue puts whole invocations on `cdp_cyclotron_*` topics as plaintext JSON (`job-queue-kafka.ts:98`), and the events topics carry every person property. Encrypting one more topic doesn't change who can read what.
- **The fingerprint threat is weak.** To brute-force a login code from it you need read access to the cyclotron database, every other field of the request, and a key that was sent at all. And the code expires within minutes. The job row next to it held the code in plaintext anyway.
- **The job row lives seconds.** The janitor deletes it about 10s after the job finishes. Encrypting it adds a reader-first deploy pair and a new "can't decrypt" failure on every workflow's hot path.
- **The real leak is error text, not the body at rest.** The old dead-letter path copies `error.message`, which can quote template values, into headers that wider tooling reads. Fixed reason codes close that, and they're free.

**What this round changes.** It would undo the map's "encrypted wherever they rest", round 1 Q4, round 2 Q7 and round 5 Q1, Q2 and Q4, and keep only the error-text fix. The contracts lose `fingerprints[]`, the Fernet envelope and the codec's encryption.

**Premise.** Send bodies rest where every other CDP payload rests, in plaintext on access-controlled Kafka and Postgres. The design protects against the one leak that's specific to it: error text quoting template values.

❓ **Q1** - **Drop `EncryptedFields` from the design**: should the intake topics, the dead-letter topic and job rows carry plaintext, like `cdp_cyclotron_*`? And should the fingerprint stay the plain SHA-256 that #132891 already has?

➡️ Yes.

- It removes the HMAC and its key rotation, the Fernet envelope, the job-state format change with its two deploys, and the breaker's main reason to exist.
- #132891 merges as it is.
- The risk that's left is the same one PostHog accepts for every Kafka topic today.

---

❓ **Q2** - **Keep the cheap protections**: should the design keep these three?

- dead-letter headers carry only a fixed reason code, never `error.message`
- the new consumer never logs a body or a variable
- the dead-letter topic keeps 7 days' retention

➡️ Yes. They cost nothing, and they cover the actual leak path the groundwork found.

---

❓ **Q3** - **The codec move becomes a follow-up**: should moving the job codec into `cyclotron-v2` drop out of this change?

- Its main reason was a single home for row encryption.
- What's left is breaking a 3-file import cycle.

➡️ Yes, a follow-up. Without encryption it moves no seam this change moves, and it's one less refactor PR to review.

---

❓ **Q4** - **Keep the name "intake"**: should the topics stay `cdp_intake_*`, rather than taking "capture" or "ingestion"?

- Both of those already name specific systems:
  - "capture" is the Rust event capture service that answers SDK requests.
  - "ingestion" is the event pipeline in `nodejs/src/ingestion/`, with its own consumers, dashboards and alerts.
- The analogy holds: the route does what capture does (accept, produce, ack), and the consumer does what ingestion does.

➡️ Keep "intake".

- `cdp_capture_*` or `cdp_ingestion_*` would make on-call and grep reach for the event pipeline first.
- The doc can say "intake is capture and ingestion for workflow runs" in one line.

---

❓ **Q5** - **No ADRs**: should the decisions live in the capture doc and the resolution comment, with no separate ADR files? An ADR, an architecture decision record, is a short file in the repo that records one hard-to-reverse decision and why. The repo barely uses them (only `products/review_hog/adr/`).

➡️ Yes, no ADRs. The capture doc's decision list carries the "why" for each seam, and the spec ticket picks it up from there.
