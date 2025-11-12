import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KafkaProducerWrapper } from '~/kafka/producer'

import { KafkaConsumer, parseKafkaHeaders } from '../kafka/consumer'
import { HealthCheckResult, Hub, LogsIngestionConsumerConfig, PluginServerService } from '../types'
import { isDevEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'

export const logMessageDroppedCounter = new Counter({
    name: 'logs_ingestion_message_dropped_count',
    help: 'The number of logs ingestion messages dropped',
    labelNames: ['reason'],
})

export type LogsIngestionMessage = {
    token: string
    teamId: number
    message: Message
}

export class LogsIngestionConsumer {
    protected name = 'LogsIngestionConsumer'
    protected kafkaConsumer: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper

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
    ): Promise<{ backgroundTask: Promise<any>; messages: LogsIngestionMessage[] }> {
        if (!messages.length) {
            return { backgroundTask: Promise.resolve(), messages: [] }
        }

        await this.produceValidLogMessages(messages)

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: Promise.resolve(),
            messages,
        }
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
                        logger.error('missing_token_or_distinct_id')
                        // Write to DLQ topic maybe?
                        logMessageDroppedCounter.inc({ reason: 'missing_token_or_distinct_id' })
                        return
                    }

                    let team = await this.hub.teamManager.getTeamByToken(token)
                    if (isDevEnv() && token === 'phc_local') {
                        // phc_local is a special token used in dev to refer to team 1
                        team = await this.hub.teamManager.getTeam(1)
                    }

                    if (!team) {
                        // Write to DLQ topic maybe?
                        logger.error('team_not_found')
                        logMessageDroppedCounter.inc({ reason: 'team_not_found' })
                        return
                    }

                    events.push({
                        token,
                        message,
                        teamId: team.id,
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
