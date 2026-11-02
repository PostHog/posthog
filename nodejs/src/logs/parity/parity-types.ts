/**
 * Language-neutral scenario format for the logs ingestion parity corpus. The Node harness and
 * `rust/logs-ingestion` read the same fixture files, so this shape is a contract between the two
 * implementations. Change it in both places in the same commit.
 */

export type ParityHeader = [string, string]

export type ParityMessage = {
    topic: string
    partition: number
    offset: number
    timestamp: number
    headers: ParityHeader[]
    /** Base64 of the Kafka value, or null for a tombstone. */
    value_b64: string | null
}

export type ParityTeam = {
    id: number
    api_token: string
    logs_settings: Record<string, unknown> | null
}

export type ParityError = {
    name: string
    message: string
    /** Raise a `DependencyUnavailableError`, which fails the batch instead of quarantining the message. */
    dependency_unavailable: boolean
}

export type ParityProduceFault = {
    output: 'logs' | 'logs_dlq' | 'app_metrics'
    /** Match only messages whose `team_id` header has this value. Absent matches every message. */
    team_id?: string
    /** How many matching produce calls fail before calls succeed again. */
    times: number
    error: ParityError
}

export type ParityScenario = {
    name: string
    description: string
    consumer: 'logs' | 'traces'
    /** Wall clock for the whole scenario, in epoch milliseconds. */
    now_ms: number
    /** Overrides applied on top of the default consumer config. */
    config: Record<string, string | number | boolean>
    teams: ParityTeam[]
    quota_limited_tokens: string[]
    /** Team id to raw `logs_logsamplingrule`-shaped rows. */
    sampling_rules: Record<string, unknown[]>
    /** Team id to source (`logs` | `spans`) to raw retention rule rows. */
    retention_rules: Record<string, Record<string, unknown[]>>
    /** Team id to raw metric rule rows. */
    metric_rules: Record<string, unknown[]>
    /** Team id to configured pattern message keys. */
    pattern_message_keys: Record<string, string[]>
    /** Team id to the traces default retention, for the traces consumer. */
    traces_retention_days: Record<string, number>
    internal_source_policies?: Record<string, { billed: boolean; teamRules: boolean }>
    /** Tokens whose team lookup throws. */
    team_lookup_faults: Record<string, ParityError>
    produce_faults: ParityProduceFault[]
    batches: ParityMessage[][]
}

/**
 * A decoded Avro container, compared field by field. The container bytes carry a random sync
 * marker and depend on the zstd build, so two correct implementations never match byte for byte.
 */
export type ParityAvroValue = {
    kind: 'avro'
    schema: unknown
    codec: string
    records: unknown[]
}

export type ParityValue =
    | { kind: 'null' }
    /** The output value is the exact input buffer. Required where the consumer must not re-encode. */
    | { kind: 'passthrough'; batch: number; index: number }
    | ParityAvroValue
    | { kind: 'json'; json: unknown }
    | { kind: 'bytes'; sha256: string; length: number }

export type ParityOutputMessage = {
    output: string
    key: string | null
    headers: Record<string, string>
    value: ParityValue
}

export type ParityBatchResult = {
    /** `null` when the batch succeeded, else the name of the error that failed it. */
    error: string | null
}

export type ParityExpected = {
    batches: ParityBatchResult[]
    outputs: ParityOutputMessage[]
    metric_emits: { token: string; team_id: number; payload: unknown }[]
    usage_records: { team_id: number; metric: string; quantity: number; unit: string }[]
    teams_ingested: number[][]
}

export type ParityFixture = {
    scenario: ParityScenario
    expected: ParityExpected
}
