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
    /** Kafka message key, or null. */
    key: string | null
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
    /** Raise a node-rdkafka error for this librdkafka code, shaped as a delivery report. */
    kafka_code?: number
    kafka_sync?: true
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
    /** Wall clock for each batch, in epoch milliseconds. The clock does not move inside a batch. */
    batch_now_ms: number[]
    /**
     * The complete consumer config, defaults included. Defaults depend on the environment, so a
     * fixture that stored only overrides would not say what the consumer ran with.
     */
    config: Record<string, string | number | boolean>
    teams: ParityTeam[]
    quota_limited_tokens: string[]
    /** Team id to raw `logs_logsamplingrule`-shaped rows. */
    sampling_rules: Record<string, unknown[]>
    /** Team id to source (`logs` | `spans`) to raw retention rule rows. */
    retention_rules: Record<string, Record<string, unknown[]>>
    /** Team id to raw metric rule rows. */
    metric_rules: Record<string, unknown[]>
    /** Team id to configured pattern message keys. A team without an entry gets the default keys. */
    pattern_message_keys: Record<string, string[]>
    /** Team id to the traces default retention, for the traces consumer. */
    traces_retention_days: Record<string, number>
    internal_source_policies?: Record<string, { billed: boolean; teamRules: boolean }>
    /** Tokens whose team lookup throws. */
    team_lookup_faults: Record<string, ParityError>
    /** Team ids whose lookup by id (during processing) throws. Fires `times` times, then succeeds. */
    team_by_id_faults: Record<string, ParityError & { times: number }>
    /** Team ids whose lookup by id returns null, as if the team was deleted mid-batch. */
    team_by_id_missing: number[]
    /** Team ids whose metric rule fetch throws. */
    metric_rules_faults: Record<string, ParityError>
    /** Team ids whose metric emit throws. */
    metric_emit_faults: number[]
    /** Team ids whose pattern key fetch throws. Fires `times` times, then succeeds. */
    pattern_keys_faults: Record<string, ParityError & { times: number }>
    /** Optional dependencies left out of the consumer, as production does when a feature is off. */
    omit_deps: ('patternMessageKeysCache' | 'tracingConfigCache' | 'metricsEmitter' | 'samplingRulesCache')[]
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
    /** `raw` is compared exactly, so key order and number formatting are part of the contract. */
    | { kind: 'json'; raw: string; json: unknown }
    | { kind: 'bytes'; sha256: string; length: number }

export type ParityOutputMessage = {
    /** The batch whose processing produced the message. */
    batch: number
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
    /**
     * `record_group` labels the record id: rows with the same label share an id, and labels are
     * assigned in the order of the sorted rows, so no random UUID reaches the fixture.
     */
    usage_records: {
        batch: number
        team_id: number
        metric: string
        quantity: number
        unit: string
        record_group: number
    }[]
    teams_ingested: number[][]
    /** Distinct `(token, resource)` pairs the quota check was asked about. */
    quota_checks: [string, string][]
}

export type ParityFixture = {
    scenario: ParityScenario
    expected: ParityExpected
}
