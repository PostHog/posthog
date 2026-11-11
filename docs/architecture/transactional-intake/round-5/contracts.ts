// Rung 4: the interfaces at each locked seam. Spike code: it type-checks in spirit, not in the repo.

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
     * fingerprints: HMAC of the request under every ENCRYPTION_SALT_KEYS key, current key first (Q1).
     */
    idempotency?: { scope: string; key: string; fingerprints: string[] }
}

export type Recalled =
    | { status: 'absent' }
    | { status: 'replayed'; runId: string }
    | { status: 'mismatch'; runId: string }

export type Committed = { runId: string; outcome: 'created' | 'replayed' | 'mismatch' }
export type Acked = { runId: string; outcome: 'accepted' | 'replayed' | 'mismatch' }

export interface RunIntake {
    /**
     * Reads the claim without writing. Postgres only after cutover step 2; in step 1 also reads the
     * legacy Valkey marker and returns its old random id.
     * Invariant: a row counts while it is unexpired OR its job still exists (the claim's own rule).
     * Errors: throws IntakeUnavailableError when the read fails; the route answers 503.
     * Cost: one indexed primary-key read, under 5 ms p99.
     */
    recall(run: Run): Promise<Recalled>

    /**
     * committed: claims in Postgres now and returns the authoritative outcome.
     * acked: by the team's intake flag (Q6):
     *   off     → same as committed (the synchronous insert)
     *   shadow  → committed, then produce; the answer is the committed outcome
     *   async   → produce only; 'accepted' on broker ack. replayed/mismatch come only from recall.
     * Invariants:
     *   - runId = uuidv5(team, scope, key) when keyed, else the invocation's random id.
     *   - Every run, keyed or not, ends in exactly one claim row (round 4 Q3).
     *   - The lifecycle 'running' row is written only after 'created', by whoever claimed.
     *   - Order of results matches order of runs. runIds in one call must be unique.
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
 * Topics (Q3): cdp_intake_transactional_email, cdp_intake_workflow_webhook. Dead letters: cdp_intake_dlq.
 * Key: runId. Producer: enable.idempotence (acks=all), snappy, message.max.bytes 2 MB,
 * message.timeout.ms = route deadline.
 * Headers (plaintext, never secret): intake_version, team_id, run_kind, run_id.
 * Value: EncryptedFields.encrypt(JSON.stringify(IntakeMessage)), a Fernet token.
 */
export type IntakeMessage = {
    v: 1
    run: Run // invocation state included; recipient, variables and body live only in here
    acceptedAt: string // ISO time of the broker-ack request, for the send-by deadline
    sendBy?: string // ISO; past it the consumer writes a failed row (#132733 PR 7)
}

// ─── 3. The dead-letter record ───────────────────────────────────────────────────────────────────

/**
 * Value: the original message bytes, unchanged and still encrypted.
 * Headers: the original headers, plus CdpDeadLetterService's names so a replay consumer reads both:
 *   dlq_step     'decode' | 'schema'
 *   dlq_class    'no_key_decrypts' | 'not_json' | 'schema_invalid'   (a fixed code, never error text)
 *   dlq_topic, dlq_partition, dlq_offset, dlq_timestamp, dlq_team_id, dlq_consumer_group
 * Breaker: more than 2 and over 10% of a batch would dead-letter → throw, the partition stalls.
 * Alert: any write to cdp_intake_dlq pages.
 */
export type IntakeDeadLetterClass = 'no_key_decrypts' | 'not_json' | 'schema_invalid'

// ─── 4. The claim (cyclotron-v2 manager, amends #132891 before it merges) ────────────────────────

export type CyclotronV2IdempotentJobInit = {
    job: CyclotronV2JobInit & { id: string } // id = runId
    /** Current key first; stored as given. A stored value matching any entry is a replay (Q1). */
    fingerprints: string[]
}

export interface CyclotronV2Claims {
    /**
     * Unchanged from #132891 except fingerprints[]: key row + job in one transaction, ids sorted.
     * Throws on duplicate ids, on a schema failure, and on any database error, for the whole call.
     */
    createJobsIdempotently(inputs: CyclotronV2IdempotentJobInit[]): Promise<('created' | 'replayed' | 'mismatch')[]>

    /** Same retention rule as the claim: unexpired, or its job still exists. Null when absent. */
    findIdempotencyKey(id: string): Promise<{ fingerprint: string } | null>
}

// ─── 5. The job codec (cyclotron-v2/codec.ts, moved by a pure-move PR first) ─────────────────────

export interface JobCodec {
    /**
     * Reader-first rollout (Q4): deploy A decodes both formats and still encodes plaintext;
     * deploy B encodes encrypted. Rolling back B to A is safe; back past A is not.
     * Encrypted state starts with a one-byte format marker, then the Fernet token.
     */
    encode(invocation: CyclotronJobInvocation): Buffer
    /** Throws JobStateUndecryptableError when no key decrypts; the janitor fails such a job. */
    decode(row: CyclotronV2DequeuedJob): CyclotronJobInvocation
}

// ─── 6. TransactionalEmail ───────────────────────────────────────────────────────────────────────

export type Outcome =
    | { kind: 'accepted' | 'replayed'; invocationId: string } // 202
    | { kind: 'mismatch' } // 422 idempotency_key_reused
    | { kind: 'refused'; code: RefusalCode } // 4xx by code, unchanged from today
    | { kind: 'invalid'; issues: unknown } // 400
    | { kind: 'too_large' } // 413, before auth-heavy checks
    | { kind: 'unavailable' } // 503 intake_unavailable

export interface TransactionalEmail {
    /**
     * Order: validate + size cap → fingerprint → recall → refusals (time budget) → launch acked.
     * A recall hit answers before refusals, so a retry of a sent email replays after a block.
     * Gone after cutover step 2: 409 idempotency_key_in_flight, 503 idempotency_unavailable.
     */
    accept(request: TransactionalEmailRequest, team: Team): Promise<Outcome>
}

// ─── 7. The fingerprint ──────────────────────────────────────────────────────────────────────────

/** HMAC-SHA256 of the canonical request under each ENCRYPTION_SALT_KEYS key, current first. */
export declare function fingerprints(canonicalRequest: string): string[]

// Placeholder types for the spike.
type CyclotronJobInvocation = unknown
type CyclotronJobInvocationHogFlow = unknown
type CyclotronV2JobInit = { teamId: number }
type CyclotronV2DequeuedJob = unknown
type RefusalCode = string
type TransactionalEmailRequest = unknown
type Team = unknown
