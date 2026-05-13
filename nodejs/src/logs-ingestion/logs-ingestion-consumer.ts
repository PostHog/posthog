import { trace } from '@opentelemetry/api'
import { Message } from 'node-rdkafka'
import pLimit from 'p-limit'
import { Counter } from 'prom-client'

import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { AppMetricsOutput } from '~/ingestion/common/outputs'
import { IngestionOutputs } from '~/ingestion/outputs/ingestion-outputs'
import type { LogsSettings } from '~/types'

import { KafkaConsumerInterface, createKafkaConsumer, parseKafkaHeaders } from '../kafka/consumer'
import { HealthCheckResult, PluginServerService } from '../types'
import { isDevEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'
import { TeamManager } from '../utils/team-manager'
import { LogsIngestionConsumerConfig } from './config'
import { type PiiScrubStats } from './log-pii-scrub'
import { processLogMessageBuffer } from './log-record-avro'
import { LOGS_DLQ_OUTPUT, LOGS_OUTPUT, LogsDlqOutput, LogsOutput } from './outputs/outputs'
import type { CompiledRuleSet } from './sampling/evaluate'
import { type SamplingRateContext, processBufferWithSampling } from './sampling/process-buffer-with-sampling'
import { SamplingRulesCache } from './sampling/sampling-rules-cache'
import { LogsRateLimiterService } from './services/logs-rate-limiter.service'
import { LogsIngestionMessage } from './types'

export interface LogsIngestionConsumerDeps {
    teamManager: TeamManager
    quotaLimiting: QuotaLimiting
    /** When set, enabled teams may run head sampling before ClickHouse Kafka produce. */
    samplingRulesCache?: SamplingRulesCache
    /**
     * Resolved outputs registry — must include `LOGS_OUTPUT`, `LOGS_DLQ_OUTPUT`,
     * and `APP_METRICS_OUTPUT`. The producer + topic for each is wired by the
     * server via env vars — this consumer never touches a `KafkaProducerWrapper`
     * directly.
     */
    outputs: IngestionOutputs<LogsOutput | LogsDlqOutput | AppMetricsOutput>
}

export type UsageStats = {
    bytesReceived: number
    recordsReceived: number
    bytesAllowed: number
    recordsAllowed: number
    bytesDropped: number
    recordsDropped: number
    piiReplacements: number
}

const DEFAULT_USAGE_STATS: UsageStats = {
    bytesReceived: 0,
    recordsReceived: 0,
    bytesAllowed: 0,
    recordsAllowed: 0,
    bytesDropped: 0,
    recordsDropped: 0,
    piiReplacements: 0,
}

export type UsageStatsByTeam = Map<number, UsageStats>

/** Ingestion default when `logs_settings.retention_days` is unset; must be in `TeamSerializer.VALID_RETENTION_DAYS`. */
export const DEFAULT_LOGS_RETENTION_DAYS = 14

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
    help: 'Total uncompressed bytes allowed through quota and rate limiting',
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
    help: 'Total log records allowed through quota and rate limiting',
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

export class LogsIngestionConsumer {
    protected name = 'LogsIngestionConsumer'
    protected kafkaConsumer: KafkaConsumerInterface
    private appMetricsAggregator: AppMetricsAggregator
    private redis: RedisV2
    private rateLimiter: LogsRateLimiterService
    private readonly logsSamplingRateLimitTtlSeconds: number
    private readonly samplingEnabledTeamsRaw: string
    private readonly samplingKillswitch: boolean

    protected groupId: string
    protected topic: string

    constructor(
        config: LogsIngestionConsumerConfig,
        private deps: LogsIngestionConsumerDeps,
        overrides: Partial<LogsIngestionConsumerConfig> = {}
    ) {
        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = overrides.LOGS_INGESTION_CONSUMER_GROUP_ID ?? config.LOGS_INGESTION_CONSUMER_GROUP_ID
        this.topic = overrides.LOGS_INGESTION_CONSUMER_CONSUME_TOPIC ?? config.LOGS_INGESTION_CONSUMER_CONSUME_TOPIC

        this.appMetricsAggregator = new AppMetricsAggregator(deps.outputs)

        this.kafkaConsumer = createKafkaConsumer({ groupId: this.groupId, topic: this.topic })
        // Logs ingestion uses its own Redis instance with TLS support
        this.redis = createRedisV2PoolFromConfig({
            connection:
                (overrides.LOGS_REDIS_HOST ?? config.LOGS_REDIS_HOST)
                    ? {
                          url: overrides.LOGS_REDIS_HOST ?? config.LOGS_REDIS_HOST,
                          options: {
                              port: overrides.LOGS_REDIS_PORT ?? config.LOGS_REDIS_PORT,
                              tls: (overrides.LOGS_REDIS_TLS ?? config.LOGS_REDIS_TLS) ? {} : undefined,
                          },
                          name: 'logs-redis',
                      }
                    : { url: config.REDIS_URL, name: 'logs-redis-fallback' },
            poolMinSize: config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        })
        this.rateLimiter = new LogsRateLimiterService(config, this.redis)
        this.logsSamplingRateLimitTtlSeconds = config.LOGS_LIMITER_TTL_SECONDS
        this.samplingEnabledTeamsRaw = overrides.LOGS_SAMPLING_ENABLED_TEAMS ?? config.LOGS_SAMPLING_ENABLED_TEAMS
        this.samplingKillswitch = overrides.LOGS_SAMPLING_KILLSWITCH ?? config.LOGS_SAMPLING_KILLSWITCH
    }

    private isSamplingEvalEnabledForTeam(teamId: number): boolean {
        if (this.samplingKillswitch) {
            return false
        }
        const raw = (this.samplingEnabledTeamsRaw || '').trim()
        if (!raw) {
            return false
        }
        if (raw === '*') {
            return true
        }
        return raw
            .split(',')
            .map((s) => parseInt(s.trim(), 10))
            .filter((n) => !Number.isNaN(n))
            .includes(teamId)
    }

    /**
     * Decode + optional head sampling, or passthrough `processLogMessageBuffer`.
     * `sampling_all_dropped` means do not enqueue to logs output (message fully sampled out).
     */
    private async resolveLogMessageBufferWithOptionalSampling(
        message: LogsIngestionMessage,
        logsSettings: LogsSettings
    ): Promise<
        | {
              outcome: 'produce'
              processedValue: Buffer
              pii: PiiScrubStats
              recordsDropped: number
              recordsDroppedByRuleId: Map<string, number>
          }
        | {
              outcome: 'sampling_all_dropped'
              pii: PiiScrubStats
              recordsDropped: number
              recordsDroppedByRuleId: Map<string, number>
          }
    > {
        const samplingCache = this.deps.samplingRulesCache
        const samplingEvalEnabled = this.isSamplingEvalEnabledForTeam(message.teamId)
        let ruleSet: CompiledRuleSet | null = null
        if (samplingCache && samplingEvalEnabled) {
            ruleSet = await samplingCache.getCompiledRuleSet(message.teamId)
        }
        const useSamplingPipeline = Boolean(ruleSet && ruleSet.rules.length > 0)

        trace.getActiveSpan()?.setAttributes({
            'logs.sampling.killswitch': this.samplingKillswitch,
            'logs.sampling.enabled_teams_configured': Boolean((this.samplingEnabledTeamsRaw || '').trim()),
            'logs.sampling.enabled_teams_is_wildcard': (this.samplingEnabledTeamsRaw || '').trim() === '*',
            'logs.sampling.cache_present': Boolean(samplingCache),
            'logs.sampling.eval_enabled_for_team': samplingEvalEnabled,
            'logs.sampling.compiled_rule_count': ruleSet?.rules.length ?? 0,
            'logs.sampling.pipeline': useSamplingPipeline
                ? 'decode_sample_encode'
                : 'passthrough_processLogMessageBuffer',
        })

        if (useSamplingPipeline && ruleSet) {
            const rateCtx: SamplingRateContext | null = ruleSet.hasRateLimitRules
                ? {
                      teamId: message.teamId,
                      redis: this.redis,
                      ttlSeconds: this.logsSamplingRateLimitTtlSeconds,
                  }
                : null
            const sampled = await processBufferWithSampling(message.message.value!, logsSettings, ruleSet, rateCtx)
            if (sampled.recordsDropped > 0) {
                logsSamplingRecordsDroppedCounter.inc({ team_id: message.teamId.toString() }, sampled.recordsDropped)
            }
            if (sampled.allDropped) {
                return {
                    outcome: 'sampling_all_dropped',
                    pii: sampled.pii,
                    recordsDropped: sampled.recordsDropped,
                    recordsDroppedByRuleId: sampled.recordsDroppedByRuleId,
                }
            }
            return {
                outcome: 'produce',
                processedValue: sampled.value,
                pii: sampled.pii,
                recordsDropped: sampled.recordsDropped,
                recordsDroppedByRuleId: sampled.recordsDroppedByRuleId,
            }
        }

        const res = await processLogMessageBuffer(message.message.value!, logsSettings)
        return {
            outcome: 'produce',
            processedValue: res.value,
            pii: res.pii,
            recordsDropped: 0,
            recordsDroppedByRuleId: new Map(),
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

        return {
            // Produce first so PII replacement counts are folded into `usageStats` before MSK usage emit
            backgroundTask: (async () => {
                await this.processAndProduceLogMessages(rateLimiterAllowedMessages, usageStats)
                await this.emitUsageMetrics(usageStats)
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
    }

    private trackOutgoingTrafficAndBuildUsageStats(
        allowedMessages: LogsIngestionMessage[],
        droppedMessages: LogsIngestionMessage[]
    ): UsageStatsByTeam {
        let totalBytesAllowed = 0
        let totalRecordsAllowed = 0
        const usageStats: UsageStatsByTeam = new Map()

        for (const message of allowedMessages) {
            const stats = usageStats.get(message.teamId) || { ...DEFAULT_USAGE_STATS }
            stats.bytesReceived += message.bytesUncompressed
            stats.recordsReceived += message.recordCount
            stats.bytesAllowed += message.bytesUncompressed
            stats.recordsAllowed += message.recordCount
            usageStats.set(message.teamId, stats)

            totalBytesAllowed += message.bytesUncompressed
            totalRecordsAllowed += message.recordCount
        }

        logsBytesAllowedCounter.inc(totalBytesAllowed)
        logsRecordsAllowedCounter.inc(totalRecordsAllowed)

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
        }

        return usageStats
    }

    private addPiiStatsIntoUsage(usage: UsageStatsByTeam, teamId: number, delta: PiiScrubStats): void {
        if (delta.piiReplacements === 0) {
            return
        }
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
                        (await this.deps.quotaLimiting.isTeamTokenQuotaLimited(token, 'logs_mb_ingested'))
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
        }

        return { rateLimiterAllowedMessages: allowed, rateLimiterDroppedMessages: dropped }
    }

    private async processAndProduceLogMessages(
        messages: LogsIngestionMessage[],
        usageStats: UsageStatsByTeam
    ): Promise<void> {
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

                        // ignore empty messages
                        if (message.message.value === null) {
                            return Promise.resolve()
                        }
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
                            async () => this.resolveLogMessageBufferWithOptionalSampling(message, logsSettings)
                        )
                        if (resolved.outcome === 'sampling_all_dropped') {
                            logMessageDroppedCounter.inc(
                                { reason: 'sampling_all_dropped', team_id: message.teamId.toString() },
                                1
                            )
                            this.addPiiStatsIntoUsage(usageStats, message.teamId, resolved.pii)
                            this.queueSamplingRecordsDroppedByRule(message.teamId, resolved.recordsDroppedByRuleId)
                            return Promise.resolve()
                        }
                        const { processedValue, pii, recordsDroppedByRuleId } = resolved
                        this.addPiiStatsIntoUsage(usageStats, message.teamId, pii)
                        this.queueSamplingRecordsDroppedByRule(message.teamId, recordsDroppedByRuleId)

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
    }

    private async produceToDlq(message: LogsIngestionMessage, error: unknown): Promise<void> {
        const errorMessage = error instanceof Error ? error.message : String(error)
        const errorName = error instanceof Error ? error.name : 'UnknownError'

        logMessageDlqCounter.inc({ reason: errorName, team_id: message.teamId.toString() })

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
            this.queueUsageMetric(teamId, 'records_ingested', stats.recordsAllowed)
            this.queueUsageMetric(teamId, 'bytes_dropped', stats.bytesDropped)
            this.queueUsageMetric(teamId, 'records_dropped', stats.recordsDropped)
            this.queueUsageMetric(teamId, 'pii_replacements', stats.piiReplacements)
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
            app_source: 'logs',
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
                app_source: 'logs',
                app_source_id: '',
                instance_id: ruleId,
                metric_kind: 'usage',
                metric_name: 'sampling_records_dropped_by_rule',
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
                        logger.error('missing_token')
                        logMessageDroppedCounter.inc({ reason: 'missing_token', team_id: 'unknown' })
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
                        return
                    }

                    if (!team) {
                        logger.error('team_not_found', { token_with_no_team: token })
                        logMessageDroppedCounter.inc({ reason: 'team_not_found', team_id: 'unknown' })
                        return
                    }

                    const bytesUncompressed = parseInt(headers.bytes_uncompressed ?? '0', 10)
                    const bytesCompressed = parseInt(headers.bytes_compressed ?? '0', 10)
                    const recordCount = parseInt(headers.record_count ?? '0', 10)

                    events.push({
                        token,
                        message,
                        teamId: team.id,
                        bytesUncompressed,
                        bytesCompressed,
                        recordCount,
                    })
                } catch (e) {
                    logger.error('Error parsing message', e)
                    logMessageDroppedCounter.inc({ reason: 'parse_error', team_id: 'unknown' })
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
