import { trace } from '@opentelemetry/api'
import { Message } from 'node-rdkafka'
import pLimit from 'p-limit'
import { Counter, Histogram } from 'prom-client'

import { KafkaConsumerInterface, createKafkaConsumer, parseKafkaHeaders } from '~/common/kafka/consumer'
import { recordPiiReplacements } from '~/common/metrics/otel-metrics'
import { AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { QuotaLimiting, QuotaResource } from '~/common/services/quota-limiting.service'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { isDevEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import type { LogsSettings } from '~/types'
import { HealthCheckResult, PluginServerService } from '~/types'

import { LogsIngestionConsumerConfig } from './config'
import {
    recordLogMessageDlq,
    recordLogMessageDropped,
    recordLogsAllowed,
    recordLogsDropped,
    recordLogsReceived,
} from './ingestion-otel-metrics'
import { logsPatternForcedDecodeCounter, makePatternMaskingStage } from './log-pattern-stage'
import { type PiiScrubStats } from './log-pii-scrub'
import {
    type LogRecord,
    type LogRecordsTransform,
    bufferProcessingMode,
    processLogMessageBuffer,
} from './log-record-avro'
import type { CompiledMetricRule } from './metrics-rules/compile-metric-rules'
import { MetricRulesCache } from './metrics-rules/metric-rules-cache'
import { LogsMetricsEmitter } from './metrics-rules/metrics-emitter'
import { buildMetricRulesOtlpPayload } from './metrics-rules/otlp-payload'
import { type BatchTallies, createBatchTallies, tallyRecords } from './metrics-rules/tally'
import { LOGS_DLQ_OUTPUT, LOGS_OUTPUT, LogsDlqOutput, LogsOutput } from './outputs/outputs'
import { EMPTY_DROP_STATS, type PipelineStage } from './pipeline/log-processing-pipeline'
import type { CompiledRetentionRuleSet } from './retention/evaluate-retention'
import { RetentionRulesCache } from './retention/retention-rules-cache'
import { makeRetentionStage } from './retention/retention-stage'
import type { CompiledRuleSet } from './sampling/evaluate'
import { LogsSamplingService } from './sampling/logs-sampling.service'
import { SamplingRulesCache } from './sampling/sampling-rules-cache'
import { LogsRateLimiterService } from './services/logs-rate-limiter.service'
import { LogsTransformerService, TransformationBatchBudget } from './transformations/logs-transformer.service'
import { LogsIngestionMessage } from './types'

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
    /**
     * Resolved outputs registry — must include `LOGS_OUTPUT`, `LOGS_DLQ_OUTPUT`,
     * and `APP_METRICS_OUTPUT`. The producer + topic for each is wired by the
     * server via env vars — this consumer never touches a `KafkaProducerWrapper`
     * directly.
     */
    outputs: IngestionOutputs<LogsOutput | LogsDlqOutput | AppMetricsOutput>
}

/** Ingestion default when `logs_settings.retention_days` is unset; must be in `TeamSerializer.VALID_RETENTION_DAYS`. */
export const DEFAULT_LOGS_RETENTION_DAYS = 14

/** Retention tiers that get their own per-tier usage metric; total = sum across all tiers. */
const RETENTION_USAGE_TIERS = new Set([14, 30, 90])

function retentionBytesMetricName(retentionDays: number): string | null {
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

/** `raw` is a comma-separated team-ID list, `*` for all teams, or empty for none. */
function teamIdMatchesCsv(raw: string, teamId: number): boolean {
    const trimmed = (raw || '').trim()
    if (!trimmed) {
        return false
    }
    if (trimmed === '*') {
        return true
    }
    return trimmed
        .split(',')
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !Number.isNaN(n))
        .includes(teamId)
}

const DEFAULT_USAGE_STATS: UsageStats = {
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

/** Cap concurrent per-message processing within a single kafka batch. */
const MAX_CONCURRENT_MESSAGE_PROCESSES = 50

export const logMessageDroppedCounter = new Counter({
    name: 'logs_ingestion_message_dropped_count',
    help: 'The number of logs ingestion messages dropped',
    labelNames: ['reason', 'team_id'],
})

export const logMessageDlqCounter = new Counter({
    name: 'logs_ingestion_message_dlq_count',
    help: 'The number of logs ingestion messages sent to DLQ',
    labelNames: ['reason', 'team_id'],
})

export const logsBytesReceivedCounter = new Counter({
    name: 'logs_ingestion_bytes_received_total',
    help: 'Total uncompressed bytes received for logs ingestion',
})

export const logsBytesAllowedCounter = new Counter({
    name: 'logs_ingestion_bytes_allowed_total',
    help: 'Total uncompressed bytes allowed through quota and rate limiting. Gross of the drop-rule billing credit: billed bytes_ingested = this − logs_ingestion_billing_bytes_credited_total.',
})

export const logsBytesAllowedRecordsCounter = new Counter({
    name: 'logs_ingestion_bytes_allowed_records_total',
    help: 'Records-based uncompressed bytes (sum of per-record sizes) allowed through quota and rate limiting',
})

export const logsRecordsBytesExceedPayloadCounter = new Counter({
    name: 'logs_ingestion_records_bytes_exceed_payload_total',
    help: 'Batches where the records-based bytes sum exceeded the payload-based bytes_uncompressed header',
    labelNames: ['team_id'],
})

export const logsBytesDroppedCounter = new Counter({
    name: 'logs_ingestion_bytes_dropped_total',
    help: 'Total uncompressed bytes dropped due to quota or rate limiting',
    labelNames: ['team_id'],
})

export const logsRecordsReceivedCounter = new Counter({
    name: 'logs_ingestion_records_received_total',
    help: 'Total log records received',
})

export const logsRecordsAllowedCounter = new Counter({
    name: 'logs_ingestion_records_allowed_total',
    help: 'Total log records allowed through quota and rate limiting. Gross of the drop-rule billing credit: billed records_ingested = this − logs_ingestion_billing_records_credited_total.',
})

export const logsRecordsDroppedCounter = new Counter({
    name: 'logs_ingestion_records_dropped_total',
    help: 'Total log records dropped due to quota or rate limiting',
    labelNames: ['team_id'],
})

export const logsSamplingRecordsDroppedCounter = new Counter({
    name: 'logs_ingestion_sampling_records_dropped_total',
    help: 'Log records dropped by head sampling rules',
    labelNames: ['team_id'],
})

export const logsBytesDroppedByRuleCounter = new Counter({
    name: 'logs_ingestion_bytes_dropped_by_rule_total',
    help: 'Bytes dropped by drop rules, summed from per-row bytes_uncompressed.',
    labelNames: ['team_id'],
})

// --- Billing impact of drop rules (Tier 1) ---
export const logsBillingBytesCreditedCounter = new Counter({
    name: 'logs_ingestion_billing_bytes_credited_total',
    help: 'Uncompressed header bytes credited back to billing for rows removed by drop rules (pro-rated).',
    labelNames: ['team_id'],
})

export const logsBillingRecordsCreditedCounter = new Counter({
    name: 'logs_ingestion_billing_records_credited_total',
    help: 'Records removed by drop rules and credited back to billing.',
    labelNames: ['team_id'],
})

// --- Metric rules (generate metrics from logs) ---
export const logsMetricRulesRecordsMatchedCounter = new Counter({
    name: 'logs_metrics_rules_records_matched_total',
    help: 'Log records that matched a metric rule and fed a generated metric data point.',
    labelNames: ['team_id'],
})

export const logsMetricRulesValueSkippedCounter = new Counter({
    name: 'logs_metrics_rules_value_skipped_total',
    help: 'Records matching a value-attribute metric rule whose value was missing or non-numeric.',
    labelNames: ['team_id'],
})

export const logsMetricRulesSeriesOverflowCounter = new Counter({
    name: 'logs_metrics_rules_series_overflow_total',
    help: 'Matching records dropped because a metric rule exceeded its per-batch label-set cap.',
    labelNames: ['team_id'],
})

export const logsMetricRulesEvalErrorCounter = new Counter({
    name: 'logs_metrics_rules_eval_error_total',
    help: 'Per-record metric-rule filter evaluations that threw; the record was skipped for that rule.',
    labelNames: ['team_id'],
})

// --- Pro-rate accuracy-confidence signals (Tier 2). No team_id label — kept low-cardinality. ---
export const logsBillingProrateDivergenceHistogram = new Histogram({
    name: 'logs_ingestion_billing_prorate_divergence',
    help: 'Per-message |content-weighted − record-weighted credit| / header. High = size-skewed batch = pro-rate less trustworthy.',
    buckets: [0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1],
})

export const logsDropBatchRowsHistogram = new Histogram({
    name: 'logs_ingestion_drop_batch_rows',
    help: 'Rows per batch for messages that had drop-rule drops; small batches carry larger pro-rate error.',
    buckets: [1, 2, 5, 10, 50, 100, 500, 1000, 5000],
})

export const logsDropFractionHistogram = new Histogram({
    name: 'logs_ingestion_drop_fraction',
    help: 'Fraction of a message content dropped by drop rules; extreme fractions carry larger pro-rate error.',
    buckets: [0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1],
})

/**
 * Pro-rate a message's billable uncompressed bytes by the fraction of its content that drop
 * rules removed. Billing is on the per-message header (whole-batch wire size), but drops are
 * decided per row (content bytes), so we scale the header down by the dropped content fraction
 * to bill only what survived.
 *
 * Weights are customer-content bytes per row (body + attributes + event_name) — NOT the per-row
 * `bytes_uncompressed` field, whose near-constant denormalization overhead (duplicated resource
 * attributes, server uuid) would skew the ratio toward record-count weighting. Content weights
 * track "share of what the customer sent"; residual error vs true wire share (protobuf framing,
 * per-batch resource blocks) is small and direction-neutral. The result is always ≤ the gross
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

/**
 * Wraps a hog log transform (mutates the surviving records in place, may drop) as the last pipeline
 * `filter` stage. Partial transform drops are not billed-credited — only the all-dropped case is
 * attributed — so it reports no per-rule accounting, just the `transformations` tag when it removed
 * any record.
 */
function makeTransformStage(transform: LogRecordsTransform): PipelineStage {
    return {
        kind: 'filter',
        name: 'transformations',
        run: async (records) => {
            const before = records.length
            await transform(records)
            const stats = EMPTY_DROP_STATS()
            if (records.length < before) {
                stats.droppedBy = 'transformations'
            }
            return { kept: records, stats }
        },
    }
}

export class LogsIngestionConsumer {
    protected name = 'LogsIngestionConsumer'
    // Billing identity for quota enforcement and usage metering; overridden by subclasses (e.g. traces).
    protected quotaResource: QuotaResource = 'logs_mb_ingested'
    protected appSource = 'logs'
    protected kafkaConsumer: KafkaConsumerInterface
    private appMetricsAggregator: AppMetricsAggregator
    private redis: RedisV2
    private rateLimiter: LogsRateLimiterService
    private samplingService: LogsSamplingService
    private readonly samplingEnabledTeamsRaw: string
    private readonly samplingKillswitch: boolean
    private readonly billingProrateEnabled: boolean
    private readonly metricRulesEnabledTeamsRaw: string
    private readonly metricRulesKillswitch: boolean
    private readonly transformationsEnabledTeamsRaw: string
    private readonly transformationsKillswitch: boolean
    private readonly retentionEnabledTeamsRaw: string
    private readonly retentionKillswitch: boolean
    private readonly patternMaskingEnabledTeamsRaw: string
    private readonly patternMaskingStage: PipelineStage

    protected groupId: string
    protected topic: string

    constructor(
        config: LogsIngestionConsumerConfig,
        private deps: LogsIngestionConsumerDeps,
        overrides: Partial<LogsIngestionConsumerConfig> = {},
        // Redis key namespace for the token-bucket rate limiter. Subclasses (e.g. traces) pass
        // their own so their per-team buckets don't share state with logs. Defaults to logs.
        rateLimiterName: string = 'logs-rate-limiter'
    ) {
        // Merge overrides once so every downstream consumer reads the same effective config —
        // a per-use-site `overrides.X ?? config.X` pattern is easy to forget (the rate limiter did).
        const mergedConfig = { ...config, ...overrides }

        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = mergedConfig.LOGS_INGESTION_CONSUMER_GROUP_ID
        this.topic = mergedConfig.LOGS_INGESTION_CONSUMER_CONSUME_TOPIC

        this.appMetricsAggregator = new AppMetricsAggregator(deps.outputs)

        this.kafkaConsumer = createKafkaConsumer({ groupId: this.groupId, topic: this.topic })
        // Logs ingestion uses its own Redis instance with TLS support
        this.redis = createRedisV2PoolFromConfig({
            connection: mergedConfig.LOGS_REDIS_HOST
                ? {
                      url: mergedConfig.LOGS_REDIS_HOST,
                      options: {
                          port: mergedConfig.LOGS_REDIS_PORT,
                          tls: mergedConfig.LOGS_REDIS_TLS ? {} : undefined,
                      },
                      name: 'logs-redis',
                  }
                : { url: mergedConfig.REDIS_URL, name: 'logs-redis-fallback' },
            poolMinSize: mergedConfig.REDIS_POOL_MIN_SIZE,
            poolMaxSize: mergedConfig.REDIS_POOL_MAX_SIZE,
        })
        this.rateLimiter = new LogsRateLimiterService(mergedConfig, this.redis, rateLimiterName)
        this.samplingService = new LogsSamplingService(this.redis, mergedConfig.LOGS_LIMITER_TTL_SECONDS)
        this.samplingEnabledTeamsRaw = mergedConfig.LOGS_SAMPLING_ENABLED_TEAMS
        this.samplingKillswitch = mergedConfig.LOGS_SAMPLING_KILLSWITCH
        this.billingProrateEnabled = mergedConfig.LOGS_BILLING_PRORATE_ENABLED
        this.metricRulesEnabledTeamsRaw = mergedConfig.LOGS_METRICS_RULES_ENABLED_TEAMS
        this.metricRulesKillswitch = mergedConfig.LOGS_METRICS_RULES_KILLSWITCH
        this.transformationsEnabledTeamsRaw = mergedConfig.LOGS_TRANSFORMATIONS_ENABLED_TEAMS
        this.transformationsKillswitch = mergedConfig.LOGS_TRANSFORMATIONS_KILLSWITCH
        this.retentionEnabledTeamsRaw = mergedConfig.LOGS_RETENTION_ENABLED_TEAMS
        this.retentionKillswitch = mergedConfig.LOGS_RETENTION_KILLSWITCH
        this.patternMaskingEnabledTeamsRaw = mergedConfig.LOGS_PATTERN_MASKING_ENABLED_TEAMS
        this.patternMaskingStage = makePatternMaskingStage(
            mergedConfig.LOGS_PATTERN_MASKING_MAX_INPUT_CHARS,
            mergedConfig.LOGS_PATTERN_MASKING_MAX_OUTPUT_CHARS
        )
    }

    private isSamplingEvalEnabledForTeam(teamId: number): boolean {
        if (this.samplingKillswitch) {
            return false
        }
        return teamIdMatchesCsv(this.samplingEnabledTeamsRaw, teamId)
    }

    private isRetentionEvalEnabledForTeam(teamId: number): boolean {
        if (this.retentionKillswitch) {
            return false
        }
        return teamIdMatchesCsv(this.retentionEnabledTeamsRaw, teamId)
    }

    private isMetricRulesEnabledForTeam(teamId: number): boolean {
        if (this.metricRulesKillswitch || !this.deps.metricRulesCache || !this.deps.metricsEmitter) {
            return false
        }
        return teamIdMatchesCsv(this.metricRulesEnabledTeamsRaw, teamId)
    }

    private isTransformationsEnabledForTeam(teamId: number): boolean {
        if (this.transformationsKillswitch || !this.deps.logsTransformer) {
            return false
        }
        return teamIdMatchesCsv(this.transformationsEnabledTeamsRaw, teamId)
    }

    /**
     * Logs only. `TracesIngestionConsumer` subclasses this one and reads the same config key, but a
     * trace record has no `body` field, so masking one measures nothing and would mix trace shapes
     * into the log-body split these metrics exist to produce.
     */
    private isPatternMaskingEnabledForTeam(teamId: number): boolean {
        return this.appSource === 'logs' && teamIdMatchesCsv(this.patternMaskingEnabledTeamsRaw, teamId)
    }

    /**
     * Builds the hog log transformation hook for a message, or undefined when the team
     * is not gated in or has no enabled transformation_log functions (the existence
     * check is an in-process cache hit, preserving the no-decode passthrough).
     */
    private async buildRecordsTransform(
        message: LogsIngestionMessage,
        batchBudget?: TransformationBatchBudget
    ): Promise<LogRecordsTransform | undefined> {
        const transformer = this.deps.logsTransformer
        if (!transformer || !this.isTransformationsEnabledForTeam(message.teamId)) {
            return undefined
        }
        if (!(await transformer.teamHasTransformations(message.teamId))) {
            return undefined
        }
        return (records) => transformer.transformRecords(message.teamId, records, batchBudget)
    }

    /**
     * Decode + optional head sampling, or passthrough `processLogMessageBuffer`.
     * `all_dropped` means do not enqueue to logs output (every record was sampled out
     * or dropped by transformations); `reason` distinguishes the source.
     */
    private async resolveLogMessageBufferWithOptionalSampling(
        message: LogsIngestionMessage,
        logsSettings: LogsSettings,
        onRecordsDecoded?: (records: LogRecord[]) => void,
        batchBudget?: TransformationBatchBudget
    ): Promise<
        | {
              outcome: 'produce'
              processedValue: Buffer
              pii: PiiScrubStats
              recordsDropped: number
              recordsDroppedByRuleId: Map<string, number>
              bytesDroppedByRuleId: Map<string, number>
              contentBytesDropped: number
              contentBytesTotal: number
          }
        | {
              outcome: 'all_dropped'
              reason: 'sampling_all_dropped' | 'transformations_all_dropped' | 'empty_batch'
              pii: PiiScrubStats
              recordsDropped: number
              recordsDroppedByRuleId: Map<string, number>
              bytesDroppedByRuleId: Map<string, number>
              contentBytesDropped: number
              contentBytesTotal: number
          }
    > {
        const samplingCache = this.deps.samplingRulesCache
        const samplingEvalEnabled = this.isSamplingEvalEnabledForTeam(message.teamId)
        let ruleSet: CompiledRuleSet | null = null
        if (samplingCache && samplingEvalEnabled) {
            ruleSet = await samplingCache.getCompiledRuleSet(message.teamId)
        }
        const useSamplingPipeline = Boolean(ruleSet && ruleSet.rules.length > 0)
        const recordsTransform = await this.buildRecordsTransform(message, batchBudget)

        // Per-row retention: resolve the team's retention rules when enabled. Any matching rule stamps
        // `retention_days` per surviving record (falling back to the team default), which ClickHouse
        // reads in place of the batch `retention-days` header. With no rules the header — still emitted
        // below — carries the team default, keeping this a no-decode passthrough.
        const retentionCache = this.deps.retentionRulesCache
        const retentionEvalEnabled = this.isRetentionEvalEnabledForTeam(message.teamId)
        let retentionRuleSet: CompiledRetentionRuleSet | null = null
        if (retentionCache && retentionEvalEnabled) {
            retentionRuleSet = await retentionCache.getCompiledRuleSet(message.teamId)
        }
        const useRetention = Boolean(retentionRuleSet && retentionRuleSet.rules.length > 0)

        // Assemble the ordered decode → transform → encode pipeline: sampling drop rules + rate limits
        // first, hog transformations next, per-row retention stamping last (so it only stamps
        // survivors). An empty list (with no metric visitor) leaves the buffer as a no-decode passthrough
        // inside `processLogMessageBuffer`.
        const stages: PipelineStage[] = []
        if (useSamplingPipeline && ruleSet) {
            stages.push(this.samplingService.makeSamplingStage(ruleSet, message.teamId, message.bytesUncompressed))
        }
        if (recordsTransform) {
            stages.push(makeTransformStage(recordsTransform))
        }
        if (useRetention && retentionRuleSet) {
            const defaultRetentionDays = logsSettings.retention_days ?? DEFAULT_LOGS_RETENTION_DAYS
            stages.push(makeRetentionStage(retentionRuleSet, message.teamId, defaultRetentionDays))
        }

        // Runs last so it only sees survivors. Adding any stage forces the full decode and re-encode,
        // so a batch that would have passed through pays both, and one already decoded for a visitor
        // pays the encode. The counter prices each.
        if (this.isPatternMaskingEnabledForTeam(message.teamId)) {
            const modeWithoutMasking = bufferProcessingMode(logsSettings, stages.length, Boolean(onRecordsDecoded))
            if (modeWithoutMasking !== 'decode_and_reencode') {
                logsPatternForcedDecodeCounter.inc({ from: modeWithoutMasking })
            }
            stages.push(this.patternMaskingStage)
        }

        trace.getActiveSpan()?.setAttributes({
            'logs.sampling.killswitch': this.samplingKillswitch,
            'logs.sampling.enabled_teams_configured': Boolean((this.samplingEnabledTeamsRaw || '').trim()),
            'logs.sampling.enabled_teams_is_wildcard': (this.samplingEnabledTeamsRaw || '').trim() === '*',
            'logs.sampling.cache_present': Boolean(samplingCache),
            'logs.sampling.eval_enabled_for_team': samplingEvalEnabled,
            'logs.sampling.compiled_rule_count': ruleSet?.rules.length ?? 0,
            'logs.transformations.enabled_for_team': Boolean(recordsTransform),
            'logs.retention.cache_present': Boolean(retentionCache),
            'logs.retention.eval_enabled_for_team': retentionEvalEnabled,
            'logs.retention.compiled_rule_count': retentionRuleSet?.rules.length ?? 0,
            'logs.retention.use_retention': useRetention,
            'logs.sampling.pipeline': useSamplingPipeline
                ? 'decode_sample_encode'
                : recordsTransform
                  ? 'decode_transform_encode'
                  : 'passthrough',
        })

        const { value, pii, drops } = await processLogMessageBuffer(message.message.value!, logsSettings, {
            onRecordsDecoded,
            stages,
        })

        // Only the sampling stage attributes per-rule drops; the transform stage reports none, so
        // these increments are no-ops on the transform-only and passthrough paths.
        if (drops.recordsDropped > 0) {
            logsSamplingRecordsDroppedCounter.inc({ team_id: message.teamId.toString() }, drops.recordsDropped)
        }
        if (drops.bytesDropped > 0) {
            logsBytesDroppedByRuleCounter.inc({ team_id: message.teamId.toString() }, drops.bytesDropped)
        }

        if (value === null) {
            // `droppedBy` tells us which filter emptied the batch; its absence means the batch decoded
            // to zero records to begin with, so attribute it to an empty batch rather than sampling.
            const reason =
                drops.droppedBy === 'transformations'
                    ? 'transformations_all_dropped'
                    : drops.droppedBy === 'sampling'
                      ? 'sampling_all_dropped'
                      : 'empty_batch'
            return {
                outcome: 'all_dropped',
                reason,
                pii,
                recordsDropped: drops.recordsDropped,
                recordsDroppedByRuleId: drops.recordsDroppedByRuleId,
                bytesDroppedByRuleId: drops.bytesDroppedByRuleId,
                contentBytesDropped: drops.contentBytesDropped,
                contentBytesTotal: drops.contentBytesTotal,
            }
        }
        return {
            outcome: 'produce',
            processedValue: value,
            pii,
            recordsDropped: drops.recordsDropped,
            recordsDroppedByRuleId: drops.recordsDroppedByRuleId,
            bytesDroppedByRuleId: drops.bytesDroppedByRuleId,
            contentBytesDropped: drops.contentBytesDropped,
            contentBytesTotal: drops.contentBytesTotal,
        }
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    public async processBatch(
        messages: LogsIngestionMessage[]
    ): Promise<{ backgroundTask?: Promise<any>; messages: LogsIngestionMessage[] }> {
        if (!messages.length) {
            return { messages: [] }
        }

        this.trackIncomingTraffic(messages)

        const { quotaAllowedMessages, quotaDroppedMessages } = await this.filterQuotaLimitedMessages(messages)
        const { rateLimiterAllowedMessages, rateLimiterDroppedMessages } =
            await this.filterRateLimitedMessages(quotaAllowedMessages)

        const usageStats = this.trackOutgoingTrafficAndBuildUsageStats(rateLimiterAllowedMessages, [
            ...quotaDroppedMessages,
            ...rateLimiterDroppedMessages,
        ])

        // One transformation time budget shared by all messages of this batch
        const transformationBatchBudget = this.deps.logsTransformer?.startBatch()

        return {
            // Produce first so PII replacement counts are folded into `usageStats` before MSK usage emit
            backgroundTask: (async () => {
                await this.processAndProduceLogMessages(
                    rateLimiterAllowedMessages,
                    usageStats,
                    transformationBatchBudget
                )
                await this.emitUsageMetrics(usageStats)
                // Best-effort flush of transformation app metrics + function logs; never block the data path
                if (this.deps.logsTransformer) {
                    await this.deps.logsTransformer.flush().catch((error) => {
                        logger.error('Failed to flush logs transformer monitoring', { error: String(error) })
                    })
                }
            })(),
            messages: rateLimiterAllowedMessages,
        }
    }

    private trackIncomingTraffic(messages: LogsIngestionMessage[]): void {
        let totalBytesReceived = 0
        let totalRecordsReceived = 0
        for (const message of messages) {
            totalBytesReceived += message.bytesUncompressed
            totalRecordsReceived += message.recordCount
        }
        logsBytesReceivedCounter.inc(totalBytesReceived)
        logsRecordsReceivedCounter.inc(totalRecordsReceived)
        recordLogsReceived(totalBytesReceived, totalRecordsReceived)
    }

    private trackOutgoingTrafficAndBuildUsageStats(
        allowedMessages: LogsIngestionMessage[],
        droppedMessages: LogsIngestionMessage[]
    ): UsageStatsByTeam {
        let totalBytesAllowed = 0
        let totalRecordsAllowed = 0
        const usageStats: UsageStatsByTeam = new Map()

        let totalBytesAllowedRecords = 0
        for (const message of allowedMessages) {
            const stats = usageStats.get(message.teamId) || { ...DEFAULT_USAGE_STATS }
            stats.bytesReceived += message.bytesUncompressed
            stats.recordsReceived += message.recordCount
            stats.bytesAllowed += message.bytesUncompressed
            stats.recordsAllowed += message.recordCount
            stats.bytesAllowedRecords += message.bytesUncompressedRecords
            usageStats.set(message.teamId, stats)

            totalBytesAllowed += message.bytesUncompressed
            totalBytesAllowedRecords += message.bytesUncompressedRecords
            totalRecordsAllowed += message.recordCount
        }

        logsBytesAllowedRecordsCounter.inc(totalBytesAllowedRecords)
        // Gross, before the drop-rule billing credit applied in processAndProduceLogMessages (see counter help).
        logsBytesAllowedCounter.inc(totalBytesAllowed)
        logsRecordsAllowedCounter.inc(totalRecordsAllowed)
        recordLogsAllowed(totalBytesAllowed, totalRecordsAllowed)

        for (const message of droppedMessages) {
            const stats = usageStats.get(message.teamId) || { ...DEFAULT_USAGE_STATS }
            stats.bytesReceived += message.bytesUncompressed
            stats.recordsReceived += message.recordCount
            stats.bytesDropped += message.bytesUncompressed
            stats.recordsDropped += message.recordCount
            usageStats.set(message.teamId, stats)
        }

        for (const [teamId, stats] of usageStats) {
            const teamIdLabel = teamId.toString()
            if (stats.bytesDropped > 0) {
                logsBytesDroppedCounter.inc({ team_id: teamIdLabel }, stats.bytesDropped)
            }
            if (stats.recordsDropped > 0) {
                logsRecordsDroppedCounter.inc({ team_id: teamIdLabel }, stats.recordsDropped)
            }
            recordLogsDropped(teamId, stats.bytesDropped, stats.recordsDropped)
        }

        return usageStats
    }

    private addPiiStatsIntoUsage(usage: UsageStatsByTeam, teamId: number, delta: PiiScrubStats): void {
        if (delta.piiReplacements === 0) {
            return
        }
        recordPiiReplacements(this.appSource, delta.piiReplacements)
        const row = usage.get(teamId) || { ...DEFAULT_USAGE_STATS }
        row.piiReplacements += delta.piiReplacements
        usage.set(teamId, row)
    }

    private async filterQuotaLimitedMessages(
        messages: LogsIngestionMessage[]
    ): Promise<{ quotaAllowedMessages: LogsIngestionMessage[]; quotaDroppedMessages: LogsIngestionMessage[] }> {
        const quotaDroppedMessages: LogsIngestionMessage[] = []
        const quotaAllowedMessages: LogsIngestionMessage[] = []

        const uniqueTokens = [...new Set(messages.map((m) => m.token))]

        const quotaLimitedTokens = new Set(
            (
                await Promise.all(
                    uniqueTokens.map(async (token) =>
                        (await this.deps.quotaLimiting.isTeamTokenQuotaLimited(token, this.quotaResource))
                            ? token
                            : null
                    )
                )
            ).filter((token): token is string => token !== null)
        )

        const droppedCountByTeam = new Map<number, number>()
        for (const message of messages) {
            if (quotaLimitedTokens.has(message.token)) {
                quotaDroppedMessages.push(message)
                droppedCountByTeam.set(message.teamId, (droppedCountByTeam.get(message.teamId) || 0) + 1)
            } else {
                quotaAllowedMessages.push(message)
            }
        }

        for (const [teamId, count] of droppedCountByTeam) {
            logMessageDroppedCounter.inc({ reason: 'quota_limited', team_id: teamId.toString() }, count)
            recordLogMessageDropped('quota_limited', teamId.toString(), count)
        }

        return { quotaAllowedMessages, quotaDroppedMessages }
    }

    private async filterRateLimitedMessages(messages: LogsIngestionMessage[]): Promise<{
        rateLimiterAllowedMessages: LogsIngestionMessage[]
        rateLimiterDroppedMessages: LogsIngestionMessage[]
    }> {
        const { allowed, dropped } = await this.rateLimiter.filterMessages(messages)

        const droppedCountByTeam = new Map<number, number>()
        for (const message of dropped) {
            droppedCountByTeam.set(message.teamId, (droppedCountByTeam.get(message.teamId) || 0) + 1)
        }
        for (const [teamId, count] of droppedCountByTeam) {
            logMessageDroppedCounter.inc({ reason: 'rate_limited', team_id: teamId.toString() }, count)
            recordLogMessageDropped('rate_limited', teamId.toString(), count)
        }

        return { rateLimiterAllowedMessages: allowed, rateLimiterDroppedMessages: dropped }
    }

    /**
     * Per-team metric-rule tally state for one batch. Rules are fetched once per team per
     * batch (30s-cached); tallies accumulate across the batch's messages and are emitted
     * as one OTLP payload per team after produce.
     */
    private async getMetricRuleBatchState(
        byTeam: Map<number, { token: string; rules: CompiledMetricRule[]; tallies: BatchTallies }>,
        message: LogsIngestionMessage
    ): Promise<{ token: string; rules: CompiledMetricRule[]; tallies: BatchTallies } | null> {
        if (!this.isMetricRulesEnabledForTeam(message.teamId)) {
            return null
        }
        let state = byTeam.get(message.teamId)
        if (!state) {
            let rules: CompiledMetricRule[]
            try {
                rules = await this.deps.metricRulesCache!.getCompiledRules(message.teamId)
            } catch (error) {
                // Fail open: metric rules are a purely additive side feature, so a rules-fetch
                // failure (e.g. a Postgres blip) must never DLQ or block the log records —
                // skip metric generation for this team this batch instead.
                logger.warn('[logs-metric-rules] rules fetch failed — skipping metric rules for batch', {
                    teamId: message.teamId,
                    error: String(error),
                })
                return null
            }
            // Re-check after the await: concurrent messages for the same team race here,
            // and replacing an existing state would silently drop its accumulated tallies.
            state = byTeam.get(message.teamId)
            if (!state) {
                state = { token: message.token, rules, tallies: createBatchTallies() }
                byTeam.set(message.teamId, state)
            }
        }
        return state.rules.length > 0 ? state : null
    }

    private async emitMetricRuleTallies(
        byTeam: Map<number, { token: string; rules: CompiledMetricRule[]; tallies: BatchTallies }>
    ): Promise<void> {
        for (const [teamId, { token, rules, tallies }] of byTeam) {
            const teamIdLabel = teamId.toString()
            if (tallies.valueSkipped > 0) {
                logsMetricRulesValueSkippedCounter.inc({ team_id: teamIdLabel }, tallies.valueSkipped)
            }
            if (tallies.evalErrors > 0) {
                logsMetricRulesEvalErrorCounter.inc({ team_id: teamIdLabel }, tallies.evalErrors)
            }
            let overflow = 0
            for (const count of tallies.seriesOverflow.values()) {
                overflow += count
            }
            if (overflow > 0) {
                logsMetricRulesSeriesOverflowCounter.inc({ team_id: teamIdLabel }, overflow)
            }
            let matched = 0
            for (const ruleTallies of tallies.byRule.values()) {
                for (const entry of ruleTallies.values()) {
                    matched += entry.count
                }
            }
            if (matched > 0) {
                logsMetricRulesRecordsMatchedCounter.inc({ team_id: teamIdLabel }, matched)
            }

            const payload = buildMetricRulesOtlpPayload(rules, tallies, Date.now())
            if (!payload) {
                continue
            }
            try {
                await this.deps.metricsEmitter!.emit(token, teamId, payload)
            } catch (error) {
                // Emission is best-effort: a failing metrics endpoint must never fail log ingestion.
                logger.warn('[logs-metric-rules] emit threw', { teamId, error: String(error) })
            }
        }
    }

    private async processAndProduceLogMessages(
        messages: LogsIngestionMessage[],
        usageStats: UsageStatsByTeam,
        transformationBatchBudget?: TransformationBatchBudget
    ): Promise<void> {
        const metricTalliesByTeam = new Map<
            number,
            { token: string; rules: CompiledMetricRule[]; tallies: BatchTallies }
        >()
        const limit = pLimit(MAX_CONCURRENT_MESSAGE_PROCESSES)
        const results = await Promise.allSettled(
            messages.map((message) =>
                limit(async () => {
                    try {
                        // Fetch team to get logs_settings
                        const team = await this.deps.teamManager.getTeam(message.teamId)
                        const logsSettings = team?.logs_settings || {}

                        // Extract settings with defaults
                        const jsonParse = logsSettings.json_parse_logs ?? false
                        const retentionDays = logsSettings.retention_days ?? DEFAULT_LOGS_RETENTION_DAYS

                        // Retention is uniform per team; stash for retention-bucketed usage emit
                        const teamStats = usageStats.get(message.teamId)
                        if (teamStats) {
                            teamStats.retentionDays = retentionDays
                        }

                        // ignore empty messages
                        if (message.message.value === null) {
                            return Promise.resolve()
                        }

                        const metricRuleState = await this.getMetricRuleBatchState(metricTalliesByTeam, message)
                        const onRecordsDecoded = metricRuleState
                            ? (records: LogRecord[]) =>
                                  tallyRecords(metricRuleState.rules, records, metricRuleState.tallies, Date.now())
                            : undefined

                        const resolved = await instrumentFn(
                            {
                                key: 'logsIngestion.sampling.resolveLogMessageBuffer',
                                measureTime: false,
                                sendException: false,
                                getLoggingContext: () => ({
                                    team_id: message.teamId,
                                    inbound_bytes: message.message.value?.length ?? 0,
                                }),
                            },
                            async () =>
                                this.resolveLogMessageBufferWithOptionalSampling(
                                    message,
                                    logsSettings,
                                    onRecordsDecoded,
                                    transformationBatchBudget
                                )
                        )

                        let bytesUncompressedHeaderOverride: number | undefined
                        let bytesCompressedHeaderOverride: number | undefined
                        let recordCountHeaderOverride: number | undefined

                        // Drop rules removed rows from this message — credit billing by the dropped
                        // content fraction. `bytesReceived` stays gross (what was sent); `bytesAllowed`
                        // (→ bytes_ingested) and `recordsAllowed` reflect only what survived the drops.
                        if (resolved.recordsDropped > 0) {
                            const header = message.bytesUncompressed
                            const contentCredit = billingByteReductionForDrops(
                                header,
                                resolved.contentBytesDropped,
                                resolved.contentBytesTotal
                            )
                            // Second estimator (record-weighted) for the accuracy-confidence signal:
                            // when content- and record-weighted credits diverge, the batch is size-skewed
                            // and the content-weighted pro-rate we bill on is less trustworthy.
                            const recordCredit = billingByteReductionForDrops(
                                header,
                                resolved.recordsDropped,
                                message.recordCount
                            )

                            const teamIdLabel = message.teamId.toString()
                            if (contentCredit > 0) {
                                logsBillingBytesCreditedCounter.inc({ team_id: teamIdLabel }, contentCredit)
                            }
                            logsBillingRecordsCreditedCounter.inc({ team_id: teamIdLabel }, resolved.recordsDropped)
                            if (message.recordCount > 0) {
                                logsDropBatchRowsHistogram.observe(message.recordCount)
                            }
                            if (resolved.contentBytesTotal > 0) {
                                logsDropFractionHistogram.observe(
                                    Math.min(1, resolved.contentBytesDropped / resolved.contentBytesTotal)
                                )
                            }
                            if (header > 0) {
                                logsBillingProrateDivergenceHistogram.observe(
                                    Math.abs(contentCredit - recordCredit) / header
                                )
                            }

                            // Shadow mode unless LOGS_BILLING_PRORATE_ENABLED: the credit above is
                            // computed and counted (observability) but billed usage is untouched.
                            if (this.billingProrateEnabled) {
                                const billingRow = usageStats.get(message.teamId)
                                if (billingRow) {
                                    billingRow.bytesAllowed = Math.max(0, billingRow.bytesAllowed - contentCredit)
                                    billingRow.recordsAllowed = Math.max(
                                        0,
                                        billingRow.recordsAllowed - resolved.recordsDropped
                                    )
                                }

                                // Scale both size headers down by the same dropped content fraction, and
                                // reduce the record count by the exact number of rows dropped, so
                                // downstream accounting sees only the surviving rows and bytes.
                                const compressedCredit = billingByteReductionForDrops(
                                    message.bytesCompressed,
                                    resolved.contentBytesDropped,
                                    resolved.contentBytesTotal
                                )
                                bytesUncompressedHeaderOverride = Math.max(0, header - contentCredit)
                                bytesCompressedHeaderOverride = Math.max(0, message.bytesCompressed - compressedCredit)
                                recordCountHeaderOverride = Math.max(0, message.recordCount - resolved.recordsDropped)
                            }
                        }

                        if (resolved.outcome === 'all_dropped') {
                            logMessageDroppedCounter.inc(
                                { reason: resolved.reason, team_id: message.teamId.toString() },
                                1
                            )
                            recordLogMessageDropped(resolved.reason, message.teamId.toString())
                            this.addPiiStatsIntoUsage(usageStats, message.teamId, resolved.pii)
                            this.queueSamplingRecordsDroppedByRule(message.teamId, resolved.recordsDroppedByRuleId)
                            this.queueBytesDroppedByRule(message.teamId, resolved.bytesDroppedByRuleId)
                            return Promise.resolve()
                        }
                        const { processedValue, pii, recordsDroppedByRuleId, bytesDroppedByRuleId } = resolved
                        this.addPiiStatsIntoUsage(usageStats, message.teamId, pii)
                        this.queueSamplingRecordsDroppedByRule(message.teamId, recordsDroppedByRuleId)
                        this.queueBytesDroppedByRule(message.teamId, bytesDroppedByRuleId)

                        // Await so a rejection here lands in the catch and routes to the DLQ.
                        await this.deps.outputs.queueMessages(LOGS_OUTPUT, [
                            {
                                value: processedValue,
                                key: null,
                                headers: {
                                    ...parseKafkaHeaders(message.message.headers),
                                    token: message.token,
                                    team_id: message.teamId.toString(),
                                    'json-parse': jsonParse.toString(),
                                    'retention-days': retentionDays.toString(),
                                    ...(bytesUncompressedHeaderOverride !== undefined
                                        ? { bytes_uncompressed: bytesUncompressedHeaderOverride.toString() }
                                        : {}),
                                    ...(bytesCompressedHeaderOverride !== undefined
                                        ? { bytes_compressed: bytesCompressedHeaderOverride.toString() }
                                        : {}),
                                    ...(recordCountHeaderOverride !== undefined
                                        ? { record_count: recordCountHeaderOverride.toString() }
                                        : {}),
                                },
                            },
                        ])
                    } catch (error) {
                        await this.produceToDlq(message, error)
                        throw error
                    }
                })
            )
        )

        const failures = results.filter((r) => r.status === 'rejected')
        if (failures.length > 0) {
            logger.error('Failed to process some log messages', {
                failureCount: failures.length,
                totalCount: messages.length,
            })
        }

        await this.emitMetricRuleTallies(metricTalliesByTeam)
    }

    private async produceToDlq(message: LogsIngestionMessage, error: unknown): Promise<void> {
        const errorMessage = error instanceof Error ? error.message : String(error)
        const errorName = error instanceof Error ? error.name : 'UnknownError'

        logMessageDlqCounter.inc({ reason: errorName, team_id: message.teamId.toString() })
        recordLogMessageDlq(errorName, message.teamId.toString())

        try {
            await this.deps.outputs.queueMessages(LOGS_DLQ_OUTPUT, [
                {
                    value: message.message.value,
                    key: null,
                    headers: {
                        ...parseKafkaHeaders(message.message.headers),
                        token: message.token,
                        team_id: message.teamId.toString(),
                        error_message: errorMessage,
                        error_name: errorName,
                        failed_at: new Date().toISOString(),
                    },
                },
            ])
        } catch (dlqError) {
            logger.error('Failed to produce message to DLQ', {
                error: dlqError,
                originalError: errorMessage,
            })
        }
    }

    private async emitUsageMetrics(usageStats: UsageStatsByTeam): Promise<void> {
        for (const [teamId, stats] of usageStats) {
            this.queueUsageMetric(teamId, 'bytes_received', stats.bytesReceived)
            this.queueUsageMetric(teamId, 'records_received', stats.recordsReceived)
            this.queueUsageMetric(teamId, 'bytes_ingested', stats.bytesAllowed)
            // Records-based counterpart to `bytes_ingested` (sum of per-record sizes instead of
            // payload size). Emitted in parallel so the two can be compared before billing
            // switches to the records-based value; not yet read by usage reports.
            this.queueUsageMetric(teamId, 'bytes_ingested_records', stats.bytesAllowedRecords)
            this.queueUsageMetric(teamId, 'records_ingested', stats.recordsAllowed)
            this.queueUsageMetric(teamId, 'bytes_dropped', stats.bytesDropped)
            this.queueUsageMetric(teamId, 'records_dropped', stats.recordsDropped)
            this.queueUsageMetric(teamId, 'pii_replacements', stats.piiReplacements)

            const retentionMetric = retentionBytesMetricName(stats.retentionDays)
            if (retentionMetric) {
                this.queueUsageMetric(teamId, retentionMetric, stats.bytesAllowed)
            }
        }

        // Best-effort: don't let metric failures block ingestion
        try {
            await this.appMetricsAggregator.flush()
        } catch (error) {
            logger.error('🔴', 'Failed to emit usage metrics - billing data may be lost', { error })
        }
    }

    private queueUsageMetric(teamId: number, metricName: string, count: number): void {
        if (count === 0) {
            return
        }
        this.appMetricsAggregator.queue({
            team_id: teamId,
            app_source: this.appSource,
            app_source_id: '',
            instance_id: '',
            metric_kind: 'usage',
            metric_name: metricName,
            count,
        })
    }

    /**
     * Per-rule head sampling drops in app_metrics2 (`sampling_records_dropped_by_rule`).
     * Team-level sampling volume in CH is `sum(count)` over those rows (no separate aggregate metric).
     */
    private queueSamplingRecordsDroppedByRule(teamId: number, byRule: Map<string, number>): void {
        for (const [ruleId, count] of byRule) {
            if (count <= 0) {
                continue
            }
            this.appMetricsAggregator.queue({
                team_id: teamId,
                app_source: this.appSource,
                app_source_id: '',
                instance_id: ruleId,
                metric_kind: 'usage',
                metric_name: 'sampling_records_dropped_by_rule',
                count,
            })
        }
    }

    /**
     * Per-rule dropped bytes in app_metrics2 (`bytes_dropped_by_rule`). Summed from per-row
     * `bytes_uncompressed`; bridges drop-rule accounting toward billing's `bytes_ingested`.
     */
    private queueBytesDroppedByRule(teamId: number, byRule: Map<string, number>): void {
        for (const [ruleId, count] of byRule) {
            if (count <= 0) {
                continue
            }
            this.appMetricsAggregator.queue({
                team_id: teamId,
                app_source: this.appSource,
                app_source_id: '',
                instance_id: ruleId,
                metric_kind: 'usage',
                metric_name: 'bytes_dropped_by_rule',
                count,
            })
        }
    }

    @instrumented('logsIngestionConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<LogsIngestionMessage[]> {
        const events: LogsIngestionMessage[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const headers = parseKafkaHeaders(message.headers)
                    const token = headers.token

                    if (!token) {
                        logger.warn('missing_token')
                        logMessageDroppedCounter.inc({ reason: 'missing_token', team_id: 'unknown' })
                        recordLogMessageDropped('missing_token', 'unknown')
                        return
                    }

                    let team
                    try {
                        if (isDevEnv() && token === 'phc_local') {
                            // phc_local is a special token used in dev to refer to team 1
                            team = await this.deps.teamManager.getTeam(1)
                        } else {
                            team = await this.deps.teamManager.getTeamByToken(token)
                        }
                    } catch (e) {
                        logger.error('team_lookup_error', { error: e })
                        logMessageDroppedCounter.inc({ reason: 'team_lookup_error', team_id: 'unknown' })
                        recordLogMessageDropped('team_lookup_error', 'unknown')
                        return
                    }

                    if (!team) {
                        // A well-formed but unknown or rotated token is a client-input problem, not a
                        // service fault. capture-logs accepts any well-formed token shape and defers team
                        // resolution to here because it has no Postgres access, so this fires on every
                        // dropped message for a bad token. Already tracked via the metrics below.
                        logger.warn('team_not_found', { token_with_no_team: token })
                        logMessageDroppedCounter.inc({ reason: 'team_not_found', team_id: 'unknown' })
                        recordLogMessageDropped('team_not_found', 'unknown')
                        return
                    }

                    const bytesUncompressed = parseInt(headers.bytes_uncompressed ?? '0', 10)
                    const bytesUncompressedRecords = parseInt(headers.bytes_uncompressed_records ?? '0', 10)
                    const bytesCompressed = parseInt(headers.bytes_compressed ?? '0', 10)
                    const recordCount = parseInt(headers.record_count ?? '0', 10)

                    if (bytesUncompressedRecords > bytesUncompressed) {
                        // Billing can only switch from payload-based to records-based bytes if the
                        // records sum never exceeds the payload size — flag any violation.
                        logsRecordsBytesExceedPayloadCounter.inc({ team_id: team.id.toString() })
                    }

                    events.push({
                        token,
                        message,
                        teamId: team.id,
                        bytesUncompressed,
                        bytesUncompressedRecords,
                        bytesCompressed,
                        recordCount,
                    })
                } catch (e) {
                    logger.error('Error parsing message', e)
                    logMessageDroppedCounter.inc({ reason: 'parse_error', team_id: 'unknown' })
                    recordLogMessageDropped('parse_error', 'unknown')
                    return
                }
            })
        )

        return events
    }

    public async processKafkaBatch(
        messages: Message[]
    ): Promise<{ backgroundTask?: Promise<any>; messages: LogsIngestionMessage[] }> {
        const events = await this._parseKafkaBatch(messages)
        return await this.processBatch(events)
    }

    public async start(): Promise<void> {
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('logsIngestionConsumer.handleEachBatch', async () => {
                return await this.processKafkaBatch(messages)
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
