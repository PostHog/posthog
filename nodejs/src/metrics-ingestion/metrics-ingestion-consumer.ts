import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KafkaProducerWrapper } from '~/kafka/producer'

import { KAFKA_APP_METRICS_2 } from '../config/kafka-topics'
import { KafkaConsumer, parseKafkaHeaders } from '../kafka/consumer'
import { HealthCheckResult, PluginServerService, TimestampFormat } from '../types'
import { isDevEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'
import { TeamManager } from '../utils/team-manager'
import { castTimestampOrNow } from '../utils/utils'
import { MetricsIngestionConsumerConfig } from './config'
import { MetricsRateLimiterService } from './services/metrics-rate-limiter.service'
import { MetricsIngestionMessage } from './types'

export interface MetricsIngestionConsumerDeps {
    teamManager: TeamManager
    quotaLimiting: QuotaLimiting
}

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

export const metricMessageDroppedCounter = new Counter({
    name: 'metrics_ingestion_message_dropped_count',
    help: 'The number of metrics ingestion messages dropped',
    labelNames: ['reason', 'team_id'],
})

export const metricMessageDlqCounter = new Counter({
    name: 'metrics_ingestion_message_dlq_count',
    help: 'The number of metrics ingestion messages sent to DLQ',
    labelNames: ['reason', 'team_id'],
})

export const metricsBytesReceivedCounter = new Counter({
    name: 'metrics_ingestion_bytes_received_total',
    help: 'Total uncompressed bytes received for metrics ingestion',
})

export const metricsBytesAllowedCounter = new Counter({
    name: 'metrics_ingestion_bytes_allowed_total',
    help: 'Total uncompressed bytes allowed through quota and rate limiting',
})

export const metricsBytesDroppedCounter = new Counter({
    name: 'metrics_ingestion_bytes_dropped_total',
    help: 'Total uncompressed bytes dropped due to quota or rate limiting',
    labelNames: ['team_id'],
})

export const metricsRecordsReceivedCounter = new Counter({
    name: 'metrics_ingestion_records_received_total',
    help: 'Total metric records received',
})

export const metricsRecordsAllowedCounter = new Counter({
    name: 'metrics_ingestion_records_allowed_total',
    help: 'Total metric records allowed through quota and rate limiting',
})

export const metricsRecordsDroppedCounter = new Counter({
    name: 'metrics_ingestion_records_dropped_total',
    help: 'Total metric records dropped due to quota or rate limiting',
    labelNames: ['team_id'],
})

export class MetricsIngestionConsumer {
    protected name = 'MetricsIngestionConsumer'
    protected kafkaConsumer: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper
    private mskProducer?: KafkaProducerWrapper
    private redis: RedisV2
    private rateLimiter: MetricsRateLimiterService

    protected groupId: string
    protected topic: string
    protected clickhouseTopic: string
    protected overflowTopic?: string
    protected dlqTopic?: string

    constructor(
        private config: MetricsIngestionConsumerConfig,
        private deps: MetricsIngestionConsumerDeps,
        overrides: Partial<MetricsIngestionConsumerConfig> = {}
    ) {
        this.groupId = overrides.METRICS_INGESTION_CONSUMER_GROUP_ID ?? config.METRICS_INGESTION_CONSUMER_GROUP_ID
        this.topic =
            overrides.METRICS_INGESTION_CONSUMER_CONSUME_TOPIC ?? config.METRICS_INGESTION_CONSUMER_CONSUME_TOPIC
        this.clickhouseTopic =
            overrides.METRICS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC ?? config.METRICS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC
        this.overflowTopic =
            overrides.METRICS_INGESTION_CONSUMER_OVERFLOW_TOPIC ?? config.METRICS_INGESTION_CONSUMER_OVERFLOW_TOPIC
        this.dlqTopic = overrides.METRICS_INGESTION_CONSUMER_DLQ_TOPIC ?? config.METRICS_INGESTION_CONSUMER_DLQ_TOPIC

        this.kafkaConsumer = new KafkaConsumer({ groupId: this.groupId, topic: this.topic })
        this.redis = createRedisV2PoolFromConfig({
            connection: config.METRICS_REDIS_HOST
                ? {
                      url: config.METRICS_REDIS_HOST,
                      options: {
                          port: config.METRICS_REDIS_PORT,
                          tls: config.METRICS_REDIS_TLS ? {} : undefined,
                      },
                      name: 'metrics-redis',
                  }
                : { url: config.REDIS_URL, name: 'metrics-redis-fallback' },
            poolMinSize: config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        })
        this.rateLimiter = new MetricsRateLimiterService(config, this.redis)
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    public async processBatch(
        messages: MetricsIngestionMessage[]
    ): Promise<{ backgroundTask?: Promise<any>; messages: MetricsIngestionMessage[] }> {
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
            backgroundTask: Promise.all([
                this.produceValidMetricMessages(rateLimiterAllowedMessages),
                this.emitUsageMetrics(usageStats),
            ]),
            messages: rateLimiterAllowedMessages,
        }
    }

    private trackIncomingTraffic(messages: MetricsIngestionMessage[]): void {
        let totalBytesReceived = 0
        let totalRecordsReceived = 0
        for (const message of messages) {
            totalBytesReceived += message.bytesUncompressed
            totalRecordsReceived += message.recordCount
        }
        metricsBytesReceivedCounter.inc(totalBytesReceived)
        metricsRecordsReceivedCounter.inc(totalRecordsReceived)
    }

    private trackOutgoingTrafficAndBuildUsageStats(
        allowedMessages: MetricsIngestionMessage[],
        droppedMessages: MetricsIngestionMessage[]
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

        metricsBytesAllowedCounter.inc(totalBytesAllowed)
        metricsRecordsAllowedCounter.inc(totalRecordsAllowed)

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
                metricsBytesDroppedCounter.inc({ team_id: teamIdLabel }, stats.bytesDropped)
            }
            if (stats.recordsDropped > 0) {
                metricsRecordsDroppedCounter.inc({ team_id: teamIdLabel }, stats.recordsDropped)
            }
        }

        return usageStats
    }

    private async filterQuotaLimitedMessages(messages: MetricsIngestionMessage[]): Promise<{
        quotaAllowedMessages: MetricsIngestionMessage[]
        quotaDroppedMessages: MetricsIngestionMessage[]
    }> {
        const quotaDroppedMessages: MetricsIngestionMessage[] = []
        const quotaAllowedMessages: MetricsIngestionMessage[] = []

        const uniqueTokens = [...new Set(messages.map((m) => m.token))]

        const quotaLimitedTokens = new Set(
            (
                await Promise.all(
                    uniqueTokens.map(async (token) =>
                        (await this.deps.quotaLimiting.isTeamTokenQuotaLimited(token, 'metrics_mb_ingested'))
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
            metricMessageDroppedCounter.inc({ reason: 'quota_limited', team_id: teamId.toString() }, count)
        }

        return { quotaAllowedMessages, quotaDroppedMessages }
    }

    private async filterRateLimitedMessages(messages: MetricsIngestionMessage[]): Promise<{
        rateLimiterAllowedMessages: MetricsIngestionMessage[]
        rateLimiterDroppedMessages: MetricsIngestionMessage[]
    }> {
        const { allowed, dropped } = await this.rateLimiter.filterMessages(messages)

        const droppedCountByTeam = new Map<number, number>()
        for (const message of dropped) {
            droppedCountByTeam.set(message.teamId, (droppedCountByTeam.get(message.teamId) || 0) + 1)
        }
        for (const [teamId, count] of droppedCountByTeam) {
            metricMessageDroppedCounter.inc({ reason: 'rate_limited', team_id: teamId.toString() }, count)
        }

        return { rateLimiterAllowedMessages: allowed, rateLimiterDroppedMessages: dropped }
    }

    private async produceValidMetricMessages(messages: MetricsIngestionMessage[]): Promise<void> {
        const results = await Promise.allSettled(
            messages.map(async (message) => {
                try {
                    if (message.message.value === null) {
                        return Promise.resolve()
                    }

                    // No enrichment needed for metrics — data is already structured numerically.
                    // Just pass through the AVRO buffer as-is.
                    return this.kafkaProducer!.produce({
                        topic: this.clickhouseTopic,
                        value: message.message.value,
                        key: null,
                        headers: {
                            ...parseKafkaHeaders(message.message.headers),
                            token: message.token,
                            team_id: message.teamId.toString(),
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
            logger.error('Failed to process some metric messages', {
                failureCount: failures.length,
                totalCount: messages.length,
            })
        }
    }

    private async produceToDlq(message: MetricsIngestionMessage, error: unknown): Promise<void> {
        if (!this.dlqTopic) {
            return
        }

        const errorMessage = error instanceof Error ? error.message : String(error)
        const errorName = error instanceof Error ? error.name : 'UnknownError'

        metricMessageDlqCounter.inc({ reason: errorName, team_id: message.teamId.toString() })

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

        const results = await Promise.allSettled(metricsPromises)
        const failures = results.filter((r) => r.status === 'rejected')
        if (failures.length > 0) {
            logger.error('Failed to emit usage metrics - billing data may be lost', {
                failureCount: failures.length,
                totalCount: metricsPromises.length,
            })
        }
    }

    private produceUsageMetric(teamId: number, metricName: string, count: number, timestamp: string): Promise<void> {
        if (count === 0) {
            return Promise.resolve()
        }
        return this.mskProducer!.produce({
            topic: KAFKA_APP_METRICS_2,
            value: Buffer.from(
                JSON.stringify({
                    team_id: teamId,
                    timestamp,
                    app_source: 'metrics',
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

    @instrumented('metricsIngestionConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<MetricsIngestionMessage[]> {
        const events: MetricsIngestionMessage[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const headers = parseKafkaHeaders(message.headers)
                    const token = headers.token

                    if (!token) {
                        logger.error('missing_token')
                        metricMessageDroppedCounter.inc({ reason: 'missing_token', team_id: 'unknown' })
                        return
                    }

                    let team
                    try {
                        team = await this.deps.teamManager.getTeamByToken(token)
                        if (isDevEnv() && token === 'phc_local') {
                            team = await this.deps.teamManager.getTeam(1)
                        }
                    } catch (e) {
                        logger.error('team_lookup_error', { error: e })
                        metricMessageDroppedCounter.inc({ reason: 'team_lookup_error', team_id: 'unknown' })
                        return
                    }

                    if (!team) {
                        logger.error('team_not_found', { token_with_no_team: token })
                        metricMessageDroppedCounter.inc({ reason: 'team_not_found', team_id: 'unknown' })
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
                    metricMessageDroppedCounter.inc({ reason: 'parse_error', team_id: 'unknown' })
                    return
                }
            })
        )

        return events
    }

    public async processKafkaBatch(
        messages: Message[]
    ): Promise<{ backgroundTask?: Promise<any>; messages: MetricsIngestionMessage[] }> {
        const events = await this._parseKafkaBatch(messages)
        return await this.processBatch(events)
    }

    public async start(): Promise<void> {
        await Promise.all([
            KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK).then((producer) => {
                this.kafkaProducer = producer
            }),
            KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK, 'METRICS_PRODUCER').then((producer) => {
                this.mskProducer = producer
            }),
        ])

        await this.kafkaConsumer.connect(async (messages) => {
            logger.info(`${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('metricsIngestionConsumer.handleEachBatch', async () => {
                return await this.processKafkaBatch(messages)
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('Stopping metrics consumer...')
        await this.kafkaConsumer.disconnect()
        await Promise.all([this.kafkaProducer?.disconnect(), this.mskProducer?.disconnect()])
        logger.info('Metrics consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
