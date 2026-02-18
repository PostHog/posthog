import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KafkaProducerWrapper } from '~/kafka/producer'

import { KAFKA_APP_METRICS_2 } from '../config/kafka-topics'
import { KafkaConsumer, parseKafkaHeaders } from '../kafka/consumer'
import { HealthCheckResult, Hub, LogsIngestionConsumerConfig, PluginServerService, TimestampFormat } from '../types'
import { isDevEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'
import { castTimestampOrNow } from '../utils/utils'
import { processLogMessageBuffer } from './log-record-avro'
import { LogsRateLimiterService } from './services/logs-rate-limiter.service'
import { LogsIngestionMessage } from './types'

/**
 * Narrowed Hub type for LogsIngestionConsumer.
 * This includes all fields needed by LogsIngestionConsumer and its dependencies:
 * - LogsRateLimiterService
 * - Redis (logs kind)
 * - KafkaProducerWrapper
 * - TeamManager
 * - QuotaLimiting (for billing quota enforcement)
 */
export type LogsIngestionConsumerHub = LogsIngestionConsumerConfig &
    Pick<
        Hub,
        // Redis config (common fields not in LogsIngestionConsumerConfig)
        | 'REDIS_URL'
        | 'REDIS_POOL_MIN_SIZE'
        | 'REDIS_POOL_MAX_SIZE'
        // KafkaProducerWrapper.create
        | 'KAFKA_CLIENT_RACK'
        // TeamManager
        | 'teamManager'
        // QuotaLimiting (billing quota enforcement)
        | 'quotaLimiting'
    >

export type UsageStats = {
    bytesReceived: number
    recordsReceived: number
    bytesAllowed: number
    recordsAllowed: number
    bytesDropped: number
    recordsDropped: number
}

const DEFAULT_USAGE_STATS: UsageStats = {
    bytesReceived: 0,
    recordsReceived: 0,
    bytesAllowed: 0,
    recordsAllowed: 0,
    bytesDropped: 0,
    recordsDropped: 0,
}

export type UsageStatsByTeam = Map<number, UsageStats>

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

export class LogsIngestionConsumer {
    protected name = 'LogsIngestionConsumer'
    protected kafkaConsumer: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper // Warpstream - for logs data
    private mskProducer?: KafkaProducerWrapper // MSK - for app_metrics
    private redis: RedisV2
    private rateLimiter: LogsRateLimiterService

    protected groupId: string
    protected topic: string
    protected clickhouseTopic: string
    protected overflowTopic?: string
    protected dlqTopic?: string

    constructor(
        private hub: LogsIngestionConsumerHub,
        overrides: Partial<LogsIngestionConsumerConfig> = {}
    ) {
        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = overrides.LOGS_INGESTION_CONSUMER_GROUP_ID ?? hub.LOGS_INGESTION_CONSUMER_GROUP_ID
        this.topic = overrides.LOGS_INGESTION_CONSUMER_CONSUME_TOPIC ?? hub.LOGS_INGESTION_CONSUMER_CONSUME_TOPIC
        this.clickhouseTopic =
            overrides.LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC ?? hub.LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC
        this.overflowTopic =
            overrides.LOGS_INGESTION_CONSUMER_OVERFLOW_TOPIC ?? hub.LOGS_INGESTION_CONSUMER_OVERFLOW_TOPIC
        this.dlqTopic = overrides.LOGS_INGESTION_CONSUMER_DLQ_TOPIC ?? hub.LOGS_INGESTION_CONSUMER_DLQ_TOPIC

        this.kafkaConsumer = new KafkaConsumer({ groupId: this.groupId, topic: this.topic })
        // Logs ingestion uses its own Redis instance with TLS support
        this.redis = createRedisV2PoolFromConfig({
            connection: hub.LOGS_REDIS_HOST
                ? {
                      url: hub.LOGS_REDIS_HOST,
                      options: {
                          port: hub.LOGS_REDIS_PORT,
                          tls: hub.LOGS_REDIS_TLS ? {} : undefined,
                      },
                      name: 'logs-redis',
                  }
                : { url: hub.REDIS_URL, name: 'logs-redis-fallback' },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        this.rateLimiter = new LogsRateLimiterService(hub, this.redis)
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
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: Promise.all([
                this.produceValidLogMessages(rateLimiterAllowedMessages),
                this.emitUsageMetrics(usageStats),
            ]),
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
                        (await this.hub.quotaLimiting.isTeamTokenQuotaLimited(token, 'logs_mb_ingested')) ? token : null
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

    private async produceValidLogMessages(messages: LogsIngestionMessage[]): Promise<void> {
        const results = await Promise.allSettled(
            messages.map(async (message) => {
                try {
                    // Fetch team to get logs_settings
                    const team = await this.hub.teamManager.getTeam(message.teamId)
                    const logsSettings = team?.logs_settings || {}

                    // Extract settings with defaults
                    const jsonParse = logsSettings.json_parse_logs ?? false
                    const retentionDays = logsSettings.retention_days ?? 15

                    // ignore empty messages
                    if (message.message.value === null) {
                        return Promise.resolve()
                    }
                    const processedValue = await processLogMessageBuffer(message.message.value, logsSettings)

                    return this.kafkaProducer!.produce({
                        topic: this.clickhouseTopic,
                        value: processedValue,
                        key: null,
                        headers: {
                            ...parseKafkaHeaders(message.message.headers),
                            token: message.token,
                            team_id: message.teamId.toString(),
                            'json-parse': jsonParse.toString(),
                            'retention-days': retentionDays.toString(),
                        },
                    })
                } catch (error) {
                    await this.produceToDlq(message, error)
                    throw error
                }
            })
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
        if (!this.dlqTopic) {
            return
        }

        const errorMessage = error instanceof Error ? error.message : String(error)
        const errorName = error instanceof Error ? error.name : 'UnknownError'

        logMessageDlqCounter.inc({ reason: errorName, team_id: message.teamId.toString() })

        try {
            await this.kafkaProducer!.produce({
                topic: this.dlqTopic,
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
            })
        } catch (dlqError) {
            logger.error('Failed to produce message to DLQ', {
                error: dlqError,
                originalError: errorMessage,
            })
        }
    }

    private async emitUsageMetrics(usageStats: UsageStatsByTeam): Promise<void> {
        if (usageStats.size === 0) {
            return
        }

        const timestamp = castTimestampOrNow(null, TimestampFormat.ClickHouse)

        const metricsPromises: Promise<void>[] = []
        for (const [teamId, stats] of usageStats) {
            metricsPromises.push(
                this.produceUsageMetric(teamId, 'bytes_received', stats.bytesReceived, timestamp),
                this.produceUsageMetric(teamId, 'records_received', stats.recordsReceived, timestamp),
                this.produceUsageMetric(teamId, 'bytes_ingested', stats.bytesAllowed, timestamp),
                this.produceUsageMetric(teamId, 'records_ingested', stats.recordsAllowed, timestamp),
                this.produceUsageMetric(teamId, 'bytes_dropped', stats.bytesDropped, timestamp),
                this.produceUsageMetric(teamId, 'records_dropped', stats.recordsDropped, timestamp)
            )
        }

        // Best-effort: don't let metric failures block ingestion
        const results = await Promise.allSettled(metricsPromises)
        const failures = results.filter((r) => r.status === 'rejected')
        if (failures.length > 0) {
            logger.error('🔴', 'Failed to emit usage metrics - billing data may be lost', {
                failureCount: failures.length,
                totalCount: metricsPromises.length,
            })
        }
    }

    private produceUsageMetric(teamId: number, metricName: string, count: number, timestamp: string): Promise<void> {
        if (count === 0) {
            return Promise.resolve()
        }
        // Use MSK producer for app_metrics, not the Warpstream producer used for logs
        return this.mskProducer!.produce({
            topic: KAFKA_APP_METRICS_2,
            value: Buffer.from(
                JSON.stringify({
                    team_id: teamId,
                    timestamp,
                    app_source: 'logs',
                    app_source_id: '',
                    instance_id: '',
                    metric_kind: 'usage',
                    metric_name: metricName,
                    count,
                })
            ),
            key: null,
        })
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
                        team = await this.hub.teamManager.getTeamByToken(token)
                        if (isDevEnv() && token === 'phc_local') {
                            // phc_local is a special token used in dev to refer to team 1
                            team = await this.hub.teamManager.getTeam(1)
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
        await Promise.all([
            // Warpstream producer for logs data (uses KAFKA_PRODUCER_* env vars)
            KafkaProducerWrapper.create(this.hub.KAFKA_CLIENT_RACK).then((producer) => {
                this.kafkaProducer = producer
            }),
            // Metrics producer for app_metrics (uses KAFKA_METRICS_PRODUCER_* env vars)
            KafkaProducerWrapper.create(this.hub.KAFKA_CLIENT_RACK, 'METRICS_PRODUCER').then((producer) => {
                this.mskProducer = producer
            }),
        ])

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
        await Promise.all([this.kafkaProducer?.disconnect(), this.mskProducer?.disconnect()])
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
