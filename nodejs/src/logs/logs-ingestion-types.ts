import { Message } from 'node-rdkafka'

import { AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { TeamManager } from '~/common/utils/team-manager'

import type { InternalSourcePolicy } from './internal-logs'
import type { MetricRulesCache } from './metrics-rules/metric-rules-cache'
import type { LogsMetricsEmitter } from './metrics-rules/metrics-emitter'
import type { LogsDlqOutput, LogsOutput } from './outputs/outputs'
import type { PatternMessageKeysCache } from './pattern-message-keys-cache'
import type { RetentionRulesCache } from './retention/retention-rules-cache'
import type { SamplingRulesCache } from './sampling/sampling-rules-cache'
import type { LogsTransformerService } from './transformations/logs-transformer.service'

export interface LogsIngestionConsumerDeps {
    teamManager: TeamManager
    quotaLimiting: QuotaLimiting
    /** When set, enabled teams may run head sampling before ClickHouse Kafka produce. */
    samplingRulesCache?: SamplingRulesCache
    /** When set (with `metricsEmitter`), enabled teams generate metrics from matching log records. */
    metricRulesCache?: MetricRulesCache
    /** OTLP sender for log-generated metrics; required alongside `metricRulesCache` to activate the feature. */
    metricsEmitter?: LogsMetricsEmitter
    /** When set, enabled teams run hog log transformations after the built-in processing. */
    logsTransformer?: LogsTransformerService
    /** When set, enabled teams stamp per-row retention from retention rules before produce. */
    retentionRulesCache?: RetentionRulesCache
    /** When set, pattern masking reads each team's message keys instead of the defaults. */
    patternMessageKeysCache?: PatternMessageKeysCache
    /**
     * Resolved outputs registry — must include `LOGS_OUTPUT`, `LOGS_DLQ_OUTPUT`,
     * and `APP_METRICS_OUTPUT`. The producer + topic for each is wired by the
     * server via env vars — this consumer never touches a `KafkaProducerWrapper`
     * directly.
     */
    outputs: IngestionOutputs<LogsOutput | LogsDlqOutput | AppMetricsOutput>
    usageBatch: UsageRecordBatch
    /**
     * Backoff for a `DependencyUnavailableError` from the team lookup or a Kafka produce. Defaults
     * to the `retryOnDependencyUnavailableError` policy (5 tries, 1 s doubling to 16 s). Tests
     * shorten it.
     */
    dependencyRetry?: { retryCount: number; initialRetryDelayMs: number }
    /** Defaults to `INTERNAL_SOURCE_POLICIES`. Tests pass a billed source, which production does not have yet. */
    internalSourcePolicies?: Readonly<Record<string, InternalSourcePolicy>>
}

/** Ingestion default when `logs_settings.retention_days` is unset; must match `DEFAULT_LOGS_RETENTION_DAYS` in `posthog/models/team/logs_retention.py`. */
export const DEFAULT_LOGS_RETENTION_DAYS = 14

// A producer can stamp internal rows with less retention than the team default.
export const INTERNAL_LOGS_MIN_RETENTION_DAYS = 1

/** Retention day counts that get their own per-tier usage metric. */
const RETENTION_USAGE_TIERS = new Set([14, 30, 90])

export function retentionBytesMetricName(retentionDays: number): string | null {
    return RETENTION_USAGE_TIERS.has(retentionDays) ? `bytes_ingested_retention_${retentionDays}d` : null
}

export type UsageStats = {
    bytesReceived: number
    recordsReceived: number
    bytesAllowed: number
    recordsAllowed: number
    /** Sum of per-record content sizes for allowed batches — billing comparison candidate for bytesAllowed. */
    bytesAllowedRecords: number
    bytesDropped: number
    recordsDropped: number
    piiReplacements: number
    retentionDays: number
}

/**
 * Per-partition offset span of a batch, for the batch log line. A consumer that dies mid-batch
 * writes nothing after it, so this is what names the records it was holding.
 */
export function describeBatchPosition(messages: Message[]): Record<string, string> {
    const spans = new Map<number, { min: number; max: number }>()
    for (const message of messages) {
        const span = spans.get(message.partition)
        if (span) {
            span.min = Math.min(span.min, message.offset)
            span.max = Math.max(span.max, message.offset)
        } else {
            spans.set(message.partition, { min: message.offset, max: message.offset })
        }
    }

    const spanByPartition: Record<string, string> = {}
    for (const [partition, { min, max }] of spans) {
        spanByPartition[partition.toString()] = min === max ? min.toString() : `${min}-${max}`
    }
    return spanByPartition
}

/**
 * Parse a batch size header, or `null` when the value is unusable. These feed usage counters and
 * billing stats, so a malformed one must not reach them: `parseInt` returns NaN for junk, and
 * prom-client's own guard treats NaN as falsy and lets it through, which leaves the counter NaN
 * for the life of the process. Parsing stays as lenient as before — only NaN and negatives, which
 * no caller can use, are rejected.
 */
export function parseSizeHeader(raw: string | undefined): number | null {
    const parsed = parseInt(raw ?? '0', 10)
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

export function parseMinTimestampHeader(raw: string | undefined): number | undefined {
    if (raw === undefined || raw.trim() === '') {
        return undefined
    }
    const parsed = Number(raw)
    return Number.isSafeInteger(parsed) ? parsed : undefined
}

export const DEFAULT_USAGE_STATS: UsageStats = {
    bytesReceived: 0,
    recordsReceived: 0,
    bytesAllowed: 0,
    recordsAllowed: 0,
    bytesAllowedRecords: 0,
    bytesDropped: 0,
    recordsDropped: 0,
    piiReplacements: 0,
    retentionDays: DEFAULT_LOGS_RETENTION_DAYS,
}

export type UsageStatsByTeam = Map<number, UsageStats>

/**
 * Pro-rate a message's billable uncompressed bytes by the fraction of its content that drop
 * rules removed. Billing is on the per-message header (whole-batch wire size), but drops are
 * decided per row (content bytes), so we scale the header down by the dropped content fraction
 * to bill only what survived.
 *
 * Weights come from `measureContentWeights`: every sender-controlled field of a row, with resource
 * and scope bytes split across the rows that share them. The per-row `bytes_uncompressed` field is
 * not used, because it counts shared resource attributes once per row. The result is always ≤ the gross
 * header (droppedFraction ≤ 1), so a message is never billed above today's gross. Returns 0 when
 * we can't measure (no header or no content bytes), i.e. no credit rather than a wrong one.
 */
export function billingByteReductionForDrops(headerBytes: number, bytesDropped: number, bytesTotal: number): number {
    if (headerBytes <= 0 || bytesDropped <= 0 || bytesTotal <= 0) {
        return 0
    }
    const droppedFraction = Math.min(1, bytesDropped / bytesTotal)
    return Math.round(headerBytes * droppedFraction)
}
