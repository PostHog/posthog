/** `rust/metrics-ingestion` reads the same fixtures, so change this shape in both places in the same commit. */
import type { ParityMessage } from '~/logs/parity/parity-types'

export type { ParityHeader, ParityMessage } from '~/logs/parity/parity-types'

/**
 * - `error`: a plain error without `isRetriable`, as a librdkafka produce error reaches the step. It is retried.
 * - `non_retriable`: a plain error with `isRetriable: false`.
 * - `dependency_unavailable`: `DependencyUnavailableError`, retriable.
 * - `message_size_too_large`: `MessageSizeTooLarge`, which the producer throws for librdkafka code 10. It is not retried.
 */
export type MetricsParityError = {
    kind: 'error' | 'non_retriable' | 'dependency_unavailable' | 'message_size_too_large'
    message: string
}

export type MetricsParityProduceFault = {
    output: 'metrics' | 'dlq' | 'app_metrics'
    team_id?: string
    times: number
    error: MetricsParityError
}

export type MetricsParityScenario = {
    name: string
    description: string
    /** The clock does not move inside a batch. */
    batch_now_ms: number[]
    /**
     * Every setting whose default depends on the environment, or that selects a step.
     * The Rust replay refuses a key it does not know.
     */
    config: Record<string, string | number | boolean>
    teams: { id: number; api_token: string }[]
    quota_limited_tokens: string[]
    team_lookup_faults: Record<string, MetricsParityError & { times: number }>
    produce_faults: MetricsParityProduceFault[]
    batches: ParityMessage[][]
}

export type MetricsParityValue =
    | { kind: 'null' }
    | { kind: 'passthrough'; batch: number; index: number }
    /** `raw` is compared exactly, so key order and number formatting are part of the contract. */
    | { kind: 'json'; raw: string; json: unknown }
    | { kind: 'bytes'; sha256: string; length: number }

export type MetricsParityOutputMessage = {
    batch: number
    output: string
    key: string | null
    /** `dlq_timestamp` is replaced by `<iso>` when it is an ISO timestamp, because Rust reads the wall clock there. */
    headers: Record<string, string>
    value: MetricsParityValue
}

export type MetricsParityExpected = {
    batches: { error: string | null }[]
    outputs: MetricsParityOutputMessage[]
    usage_records: {
        batch: number
        team_id: number
        usage_key: string
        record_id: string
        quantity: number
        unit: string
        timestamp_ms: number | null
    }[]
    /** Each call's team ids are sorted, because Node lists them in the order messages finished the team lookup. */
    teams_ingested: number[][]
    quota_checks: [string, string][]
}

export type MetricsParityFixture = {
    scenario: MetricsParityScenario
    expected: MetricsParityExpected
}
