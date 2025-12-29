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
import { LogsRateLimiterService } from './services/logs-rate-limiter.service'
import { LogsIngestionMessage } from './types'

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
    labelNames: ['reason'],
})

export const logsBytesReceivedCounter = new Counter({
    name: 'logs_ingestion_bytes_received_total',
    help: 'Total uncompressed bytes received for logs ingestion',
})

export const logsBytesAllowedCounter = new Counter({
    name: 'logs_ingestion_bytes_allowed_total',
    help: 'Total uncompressed bytes allowed through rate limiting',
})

export const logsBytesDroppedCounter = new Counter({
    name: 'logs_ingestion_bytes_dropped_total',
    help: 'Total uncompressed bytes dropped due to rate limiting',
})

export const logsRecordsReceivedCounter = new Counter({
    name: 'logs_ingestion_records_received_total',
    help: 'Total log records received',
})

export const logsRecordsAllowedCounter = new Counter({
    name: 'logs_ingestion_records_allowed_total',
    help: 'Total log records allowed through rate limiting',
})

export const logsRecordsDroppedCounter = new Counter({
    name: 'logs_ingestion_records_dropped_total',
    help: 'Total log records dropped due to rate limiting',
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
        private hub: Hub,
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
                  }
                : { url: hub.REDIS_URL },
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

        const { allowed, usageStats } = await this.filterRateLimitedMessages(messages)

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: Promise.all([this.produceValidLogMessages(allowed), this.emitUsageMetrics(usageStats)]),
            messages: allowed,
        }
    }

    private async filterRateLimitedMessages(
        messages: LogsIngestionMessage[]
    ): Promise<{ allowed: LogsIngestionMessage[]; usageStats: UsageStatsByTeam }> {
        // Track total incoming traffic
        let totalBytesReceived = 0
        let totalRecordsReceived = 0
        for (const message of messages) {
            totalBytesReceived += message.bytesUncompressed
            totalRecordsReceived += message.recordCount
        }
        logsBytesReceivedCounter.inc(totalBytesReceived)
        logsRecordsReceivedCounter.inc(totalRecordsReceived)

        // Filter messages using rate limiter service
        const { allowed, dropped } = await this.rateLimiter.filterMessages(messages)

        // Aggregate usage stats by team for app_metrics
        const usageStats: UsageStatsByTeam = new Map()

        // Track allowed metrics
        let bytesAllowed = 0
        let recordsAllowed = 0
        for (const message of allowed) {
            const stats = usageStats.get(message.teamId) || { ...DEFAULT_USAGE_STATS }
            stats.bytesReceived += message.bytesUncompressed
            stats.recordsReceived += message.recordCount
            stats.bytesAllowed += message.bytesUncompressed
            stats.recordsAllowed += message.recordCount
            usageStats.set(message.teamId, stats)
            bytesAllowed += message.bytesUncompressed
            recordsAllowed += message.recordCount
        }
        logsBytesAllowedCounter.inc(bytesAllowed)
        logsRecordsAllowedCounter.inc(recordsAllowed)

        // Track dropped metrics
        logMessageDroppedCounter.inc({ reason: 'rate_limited' }, dropped.length)

        let bytesDropped = 0
        let recordsDropped = 0
        for (const message of dropped) {
            const stats = usageStats.get(message.teamId) || { ...DEFAULT_USAGE_STATS }
            stats.bytesReceived += message.bytesUncompressed
            stats.recordsReceived += message.recordCount
            stats.bytesDropped += message.bytesUncompressed
            stats.recordsDropped += message.recordCount
            usageStats.set(message.teamId, stats)
            bytesDropped += message.bytesUncompressed
            recordsDropped += message.recordCount
        }
        logsBytesDroppedCounter.inc(bytesDropped)
        logsRecordsDroppedCounter.inc(recordsDropped)

        return { allowed, usageStats }
    }

    private async produceValidLogMessages(messages: LogsIngestionMessage[]): Promise<void> {
        await Promise.all(
            messages.map((message) => {
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
            })
        )
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
                        logMessageDroppedCounter.inc({ reason: 'missing_token' })
                        return
                    }

                    let team = await this.hub.teamManager.getTeamByToken(token)
                    if (isDevEnv() && token === 'phc_local') {
                        // phc_local is a special token used in dev to refer to team 1
                        team = await this.hub.teamManager.getTeam(1)
                    }

                    if (!team) {
                        logger.error('team_not_found', { token_with_no_team: token })
                        logMessageDroppedCounter.inc({ reason: 'team_not_found' })
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
                    logMessageDroppedCounter.inc({ reason: 'parse_error' })
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
            KafkaProducerWrapper.create(this.hub).then((producer) => {
                this.kafkaProducer = producer
            }),
            // Metrics producer for app_metrics (uses KAFKA_METRICS_PRODUCER_* env vars)
            KafkaProducerWrapper.create(this.hub, 'METRICS_PRODUCER').then((producer) => {
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
