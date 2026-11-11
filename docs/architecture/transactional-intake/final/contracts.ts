// The interfaces at each locked seam. Spike code: types are sketched, not compiled in the repo.

// ─── 1. Run intake (nodejs/src/cdp/intake/) ──────────────────────────────────────────────────────

export type RunKind = 'transactional-email' | 'workflow-webhook'

/** What a caller hands Run intake. The invocation is already built; Run intake never builds one. */
export type Run = {
    kind: RunKind
    teamId: number
    invocation: CyclotronJobInvocationHogFlow
    /**
     * Present when the caller sent an idempotency key.
     * scope: 'transactional-email', or the hog flow id for webhooks.
     * fingerprint: SHA-256 of the canonical request for sends; the flow id for webhooks.
     */
    idempotency?: { scope: string; key: string; fingerprint: string }
}

export type Recalled =
    | { status: 'absent' }
    | { status: 'replayed'; runId: string }
    | { status: 'mismatch'; runId: string }

export type Committed = { runId: string; outcome: 'created' | 'replayed' | 'mismatch' }
export type Acked = { runId: string; outcome: 'accepted' | 'replayed' | 'mismatch' }

export interface RunIntake {
    /**
     * Reads the claim without writing. In cutover step 1 it also reads the legacy Valkey marker and
     * returns its old random id; from step 2 Postgres only.
     * Invariant: a row counts while it is unexpired OR its job still exists (the claim's own rule).
     * Errors: IntakeUnavailableError when the read fails; the route answers 503.
     * Cost: one primary-key read.
     */
    recall(run: Run): Promise<Recalled>

    /**
     * committed: claims in Postgres now and returns the authoritative outcome.
     * acked: by the team's cdp-intake-kafka flag:
     *   off    → same as committed (the synchronous claim; deleted at the last Kafka step)
     *   shadow → committed, then produce; the answer is the committed outcome
     *   async  → produce only; 'accepted' on broker ack. replayed/mismatch come only from recall.
     * Invariants:
     *   - runId = uuidv5(team, scope, key) when keyed, else the invocation's random id.
     *   - Every run, keyed or not, ends in exactly one claim row, so a redelivery never starts it twice.
     *   - The lifecycle 'running' row is written only after 'created', by whoever claimed.
     *   - Results come back in the order of runs. runIds in one call must be unique.
     * Errors: IntakeUnavailableError on a Postgres error (committed) or no broker ack before the
     *   deadline (acked). Neither leaves a half-written run: the claim is one transaction, and the
     *   producer's message.timeout.ms equals the route deadline.
     * Cost: committed is one transaction; acked is one produce awaiting acks=all.
     */
    launch(runs: Run[], options: { wait: 'committed' }): Promise<Committed[]>
    launch(runs: Run[], options: { wait: 'acked' }): Promise<Acked[]>
}

export class IntakeUnavailableError extends Error {}

// ─── 2. The intake message (Kafka) ───────────────────────────────────────────────────────────────

/**
 * Topics: cdp_intake_transactional_email and cdp_intake_workflow_webhook, 18h retention, each with
 * its own consumer group. Key: runId.
 * Producer: enable.idempotence (implies acks=all; never overridden), snappy,
 * message.max.bytes 2 MB (topic max.message.bytes to match), message.timeout.ms = route deadline.
 * Headers: intake_version, team_id, run_kind, run_id.
 * Value: JSON IntakeMessage, plaintext like cdp_cyclotron_*.
 */
export type IntakeMessage = {
    v: 1
    run: Run
    acceptedAt: string // ISO time the route produced it
    sendBy?: string // ISO; past it the consumer writes a failed row (#132733 PR 7)
}

// ─── 3. The consumer's batch ─────────────────────────────────────────────────────────────────────

/**
 * 1. Parse each message; dead-letter those that can never insert.
 * 2. Dedupe by runId: first wins, the rest count as replayed.
 * 3. One createJobsIdempotently call.
 * 4. Lifecycle rows: 'running' for created, 'failed' with idempotency_key_reused for mismatch.
 * 5. Await everything, then store offsets.
 * A Postgres error retries in-process with backoff for a bounded time, storing no offsets, then throws.
 * A plain class on createKafkaConsumer, not a CdpConsumerBase subclass. Never logs a body or variable.
 */

// ─── 4. The dead-letter record ───────────────────────────────────────────────────────────────────

/**
 * Topic: cdp_intake_dlq, 7 days. Value: the original message bytes, unchanged.
 * Headers: the original headers, plus CdpDeadLetterService's names:
 *   dlq_step 'parse' | 'schema', dlq_class (below, a fixed code, never error text),
 *   dlq_topic, dlq_partition, dlq_offset, dlq_timestamp, dlq_team_id, dlq_consumer_group
 * Not dead letters: Postgres errors (retry), deleted team or disabled flow (insert; the worker
 * refuses), past send-by (failed row), mismatch (failed row).
 * Breaker: 3 or more and over 10% of a batch → throw, the partition stalls.
 * Alert: any write pages.
 */
export type IntakeDeadLetterClass = 'not_json' | 'schema_invalid'

// ─── 5. The claim (cyclotron-v2 manager; #132891 as it stands) ───────────────────────────────────

export interface CyclotronV2Claims {
    /** Key row + job in one transaction, ids sorted. Throws for the whole call on duplicate ids,
     *  a schema failure or any database error. */
    createJobsIdempotently(
        inputs: { job: CyclotronV2JobInit & { id: string }; fingerprint: string }[]
    ): Promise<('created' | 'replayed' | 'mismatch')[]>

    /** Same retention rule as the claim: unexpired, or its job still exists. Null when absent. */
    findIdempotencyKey(id: string): Promise<{ fingerprint: string } | null>
}

// ─── 6. TransactionalEmail ───────────────────────────────────────────────────────────────────────

export type Outcome =
    | { kind: 'accepted' | 'replayed'; invocationId: string } // 202
    | { kind: 'mismatch' } // 422 idempotency_key_reused
    | { kind: 'refused'; code: RefusalCode } // 4xx by code, unchanged
    | { kind: 'invalid'; issues: unknown } // 400
    | { kind: 'too_large' } // 413
    | { kind: 'unavailable' } // 503 intake_unavailable

export interface TransactionalEmail {
    /**
     * Order: validate + size cap → fingerprint → recall → refusals (time budget) → launch acked.
     * A recall hit answers before refusals, so a retry of a sent email replays after a block.
     * Gone after cutover step 2: 409 idempotency_key_in_flight, 503 idempotency_unavailable.
     */
    accept(request: TransactionalEmailRequest, team: Team): Promise<Outcome>
}

// ─── 7. The webhook route ────────────────────────────────────────────────────────────────────────

/**
 * Order: trigger template (method, auth, parse; may answer its own 4xx and queue nothing)
 * → recall when keyed (200 duplicate on replayed) → launch acked → the template's response, or 200 ok.
 * No 409: an in-flight retry gets the normal response and the consumer records it replayed.
 */

type CyclotronJobInvocationHogFlow = unknown
type CyclotronV2JobInit = { teamId: number }
type RefusalCode = string
type TransactionalEmailRequest = unknown
type Team = unknown
