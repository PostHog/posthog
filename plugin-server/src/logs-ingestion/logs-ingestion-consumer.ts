import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { RedisV2, createRedisV2Pool } from '~/common/redis/redis-v2'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KafkaProducerWrapper } from '~/kafka/producer'

import { KafkaConsumer, parseKafkaHeaders } from '../kafka/consumer'
import { HealthCheckResult, Hub, LogsIngestionConsumerConfig, PluginServerService } from '../types'
import { isDevEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'
import { LogsRateLimiterService } from './services/logs-rate-limiter.service'
import { LogsIngestionMessage } from './types'

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
    private kafkaProducer?: KafkaProducerWrapper
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
        this.redis = createRedisV2Pool(hub, 'logs')
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

        const filteredMessages = await this.filterRateLimitedMessages(messages)

        if (!filteredMessages.length) {
            return { messages: [] }
        }

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: this.produceValidLogMessages(filteredMessages),
            messages: filteredMessages,
        }
    }

    private async filterRateLimitedMessages(messages: LogsIngestionMessage[]): Promise<LogsIngestionMessage[]> {
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

        // Track allowed metrics
        let bytesAllowed = 0
        let recordsAllowed = 0
        for (const message of allowed) {
            bytesAllowed += message.bytesUncompressed
            recordsAllowed += message.recordCount
        }
        logsBytesAllowedCounter.inc(bytesAllowed)
        logsRecordsAllowedCounter.inc(recordsAllowed)

        // Track dropped metrics
        let bytesDropped = 0
        let recordsDropped = 0
        logMessageDroppedCounter.inc({ reason: 'rate_limited' }, dropped.length)
        for (const message of dropped) {
            bytesDropped += message.bytesUncompressed
            recordsDropped += message.recordCount
        }
        logsBytesDroppedCounter.inc(bytesDropped)
        logsRecordsDroppedCounter.inc(recordsDropped)

        return allowed
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
        await KafkaProducerWrapper.create(this.hub).then((producer) => {
            this.kafkaProducer = producer
        })

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
        await this.kafkaProducer?.disconnect()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
