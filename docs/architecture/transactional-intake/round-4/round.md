**What round 3 changed.** All seven call-path answers are locked. Your new proposal reopens one map decision: workflow webhooks go to Kafka too, with the trigger template run in the synchronous step. The page adds path 5 and leaves paths 1 to 4 as they were.

**Premise.** A webhook works like a send. The route runs the trigger template, and the template decides whether to reject. Only an accepted run goes to Kafka, and the route answers with the template's own response after the broker ack. The template's response never depended on the insert, so callers see no change.

❓ **Q1** - **Webhooks on Kafka**: should the webhook route launch `acked` like sends, with the trigger template running synchronously before the ack?

- This overturns the map decision that webhooks stay synchronous with no Kafka.
- Round 3's Q7 (the webhook route takes both idempotency cutover steps) still holds. The Kafka steps then follow, per team flag, as they do for sends.

➡️ Yes.

- The response comes from the template and is known before the queue step, so nothing a caller sees changes.
- Webhooks are the larger load. Taking their insert off the request path is where most of the intake's wait goes away.

---

❓ **Q2** - **A topic of their own**: should webhook runs go on their own topic and consumer group, running the same Run intake code, rather than share the intake topic with sends?

➡️ Yes.

- Webhook bursts are much larger than sends. On one topic, a burst puts a password reset behind it in the same partition.
- Separate groups also give separate lag alerts.

---

❓ **Q3** - **A claim row for every Kafka run**: should every run on the Kafka path claim a row, including keyless ones?

- A keyless run claims on its own random `runId`, under its own scope, so a redelivered batch can't start it twice.
- This applies to keyless sends as well as webhooks. It closes a gap round 1 missed.

➡️ Yes.

- Kafka delivers at least once. A consumer that crashes after the insert and before the offset store gets the batch again.
- The job row's id can't catch the repeat, because the janitor deletes it seconds after the job finishes.
- The cost is one small row per run, swept after 24h.

---

❓ **Q4** - **Recall after the template**: should the webhook route keep today's order: run the template (method, auth, parse) first, then `recall`, then launch?

➡️ Yes.

- With `recall` first, a duplicate key with a bad `Authorization` header would get `200 duplicate` instead of `401`.
- That tells an unauthenticated caller a key was used.
- It also skips the template's checks.

---

❓ **Q5** - **Message size**: should the topics' `max.message.bytes` and the producer's `message.max.bytes` allow a run built from a full 512 KB webhook body?

- That run holds the request in its globals and the captured event's properties, so it can pass 1 MB.
- The limit would be 2 MB, with snappy compression.

➡️ Yes, 2 MB, with the route's existing 512 KB cap kept as the real limit.

- The alternative, trimming the request out of the run, changes what workflow steps can read. That doesn't belong in this change.

---

❓ **Q6** - **The in-flight answer goes**: should webhooks lose `409 in_flight`, as sends do?

- A retry while the first run is still in Kafka gets the template's normal response, and the consumer records it as `replayed`.

➡️ Yes.

- On Kafka nothing is ever "pending" at the route.
- The `409` is what refused valid retries in the first place.
