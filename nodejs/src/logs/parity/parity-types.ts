/** `rust/logs-ingestion` reads the same fixtures, so change this shape in both places in the same commit. */

export type ParityHeader = [string, string]

export type ParityMessage = {
    topic: string
    partition: number
    offset: number
    timestamp: number
    key: string | null
    headers: ParityHeader[]
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
    /** Fails the batch instead of quarantining the message. */
    dependency_unavailable: boolean
    kafka_code?: number
    kafka_sync?: true
}

export type ParityProduceFault = {
    output: 'logs' | 'logs_dlq' | 'app_metrics'
    /** Absent matches every message. */
    team_id?: string
    times: number
    error: ParityError
}

export type ParityScenario = {
    name: string
    description: string
    consumer: 'logs' | 'traces'
    /** The clock does not move inside a batch. */
    batch_now_ms: number[]
    /** Defaults depend on the environment, so the fixture stores the complete config. */
    config: Record<string, string | number | boolean>
    teams: ParityTeam[]
    quota_limited_tokens: string[]
    sampling_rules: Record<string, unknown[]>
    retention_rules: Record<string, Record<string, unknown[]>>
    metric_rules: Record<string, unknown[]>
    /** A team without an entry gets the default keys. */
    pattern_message_keys: Record<string, string[]>
    traces_retention_days: Record<string, number>
    internal_source_policies?: Record<string, { billed: boolean; teamRules: boolean }>
    team_lookup_faults: Record<string, ParityError>
    team_by_id_faults: Record<string, ParityError & { times: number }>
    team_by_id_missing: number[]
    metric_rules_faults: Record<string, ParityError>
    metric_emit_faults: number[]
    pattern_keys_faults: Record<string, ParityError & { times: number }>
    omit_deps: ('patternMessageKeysCache' | 'tracingConfigCache' | 'metricsEmitter' | 'samplingRulesCache')[]
    produce_faults: ParityProduceFault[]
    batches: ParityMessage[][]
}

/** Container bytes carry a random sync marker and depend on the zstd build, so outputs compare decoded. */
export type ParityAvroValue = {
    kind: 'avro'
    schema: unknown
    codec: string
    records: unknown[]
}

export type ParityValue =
    | { kind: 'null' }
    /** Required where the consumer must not re-encode. */
    | { kind: 'passthrough'; batch: number; index: number }
    | ParityAvroValue
    /** `raw` is compared exactly, so key order and number formatting are part of the contract. */
    | { kind: 'json'; raw: string; json: unknown }
    | { kind: 'bytes'; sha256: string; length: number }

export type ParityOutputMessage = {
    batch: number
    output: string
    key: string | null
    headers: Record<string, string>
    value: ParityValue
}

export type ParityBatchResult = {
    error: string | null
}

export type ParityExpected = {
    batches: ParityBatchResult[]
    outputs: ParityOutputMessage[]
    metric_emits: { token: string; team_id: number; payload: unknown }[]
    /** Labels follow the sorted row order, so no random UUID reaches the fixture. */
    usage_records: {
        batch: number
        team_id: number
        metric: string
        quantity: number
        unit: string
        record_group: number
    }[]
    teams_ingested: number[][]
    quota_checks: [string, string][]
}

export type ParityFixture = {
    scenario: ParityScenario
    expected: ParityExpected
}
