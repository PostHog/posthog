import { Message } from 'node-rdkafka'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { KAFKA_INGESTION_WARNINGS } from '../config/kafka-topics'
import { KafkaConsumer } from '../kafka/consumer'
import { KafkaProducerWrapper } from '../kafka/producer'
import { HealthCheckResult, HealthCheckResultError, PluginServerService, PluginsServerConfig } from '../types'
import { logger } from '../utils/logger'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { TeamManager } from '../utils/team-manager'
import { EVENTS_OUTPUT, HEATMAPS_OUTPUT } from './analytics/outputs'
import {
    TestingJoinedIngestionPipelineConfig,
    TestingJoinedIngestionPipelineContext,
    TestingJoinedIngestionPipelineDeps,
    TestingJoinedIngestionPipelineInput,
    createTestingJoinedIngestionPipeline,
} from './analytics/testing-joined-ingestion-pipeline'
import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT } from './common/outputs'
import { latestOffsetTimestampGauge } from './ingestion-consumer'
import { IngestionOutputs } from './outputs/ingestion-outputs'
import { SingleIngestionOutput } from './outputs/single-ingestion-output'
import { BatchPipeline } from './pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from './pipelines/builders'
import { createOkContext } from './pipelines/helpers'

export type IngestionTestingConsumerFullConfig = Pick<
    PluginsServerConfig,
    | 'KAFKA_CLIENT_RACK'
    | 'INGESTION_CONSUMER_CONSUME_TOPIC'
    | 'INGESTION_CONSUMER_GROUP_ID'
    | 'INGESTION_CONSUMER_DLQ_TOPIC'
    | 'CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC'
    | 'CLICKHOUSE_HEATMAPS_KAFKA_TOPIC'
    | 'KAFKA_BATCH_START_LOGGING_ENABLED'
>

export interface IngestionTestingConsumerDeps {
    /** Single producer for all output (events, DLQ, internal messages) — writes to WarpStream */
    kafkaProducer: KafkaProducerWrapper
    teamManager: TeamManager
}

export class IngestionTestingConsumer {
    protected name = 'ingestion-testing-consumer'
    protected groupId: string
    protected topic: string
    protected dlqTopic: string
    protected kafkaConsumer: KafkaConsumer
    isStopping = false
    protected kafkaProducer?: KafkaProducerWrapper
    public readonly promiseScheduler = new PromiseScheduler()

    private joinedPipeline!: BatchPipeline<
        TestingJoinedIngestionPipelineInput,
        void,
        TestingJoinedIngestionPipelineContext,
        TestingJoinedIngestionPipelineContext
    >

    constructor(
        private config: IngestionTestingConsumerFullConfig,
        private deps: IngestionTestingConsumerDeps,
        overrides: Partial<
            Pick<
                PluginsServerConfig,
                'INGESTION_CONSUMER_CONSUME_TOPIC' | 'INGESTION_CONSUMER_GROUP_ID' | 'INGESTION_CONSUMER_DLQ_TOPIC'
            >
        > = {}
    ) {
        this.groupId = overrides.INGESTION_CONSUMER_GROUP_ID ?? config.INGESTION_CONSUMER_GROUP_ID
        this.topic = overrides.INGESTION_CONSUMER_CONSUME_TOPIC ?? config.INGESTION_CONSUMER_CONSUME_TOPIC
        this.dlqTopic = overrides.INGESTION_CONSUMER_DLQ_TOPIC ?? config.INGESTION_CONSUMER_DLQ_TOPIC

        this.name = `ingestion-testing-consumer-${this.topic}`

        this.kafkaConsumer = new KafkaConsumer({
            groupId: this.groupId,
            topic: this.topic,
        })

        // Single WarpStream producer used for all output (events, DLQ, internal messages)
        this.kafkaProducer = this.deps.kafkaProducer
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    public async start(): Promise<void> {
        const outputs = new IngestionOutputs({
            [EVENTS_OUTPUT]: new SingleIngestionOutput(
                EVENTS_OUTPUT,
                this.config.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                this.kafkaProducer!,
                'default'
            ),
            [HEATMAPS_OUTPUT]: new SingleIngestionOutput(
                HEATMAPS_OUTPUT,
                this.config.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                this.kafkaProducer!,
                'default'
            ),
            [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                INGESTION_WARNINGS_OUTPUT,
                KAFKA_INGESTION_WARNINGS,
                this.kafkaProducer!,
                'default'
            ),
            [DLQ_OUTPUT]: new SingleIngestionOutput(DLQ_OUTPUT, this.dlqTopic, this.kafkaProducer!, 'default'),
        })

        const joinedPipelineConfig: TestingJoinedIngestionPipelineConfig = {
            groupId: this.groupId,
            outputs,
        }
        const joinedPipelineDeps: TestingJoinedIngestionPipelineDeps = {
            promiseScheduler: this.promiseScheduler,
            teamManager: this.deps.teamManager,
        }
        this.joinedPipeline = createTestingJoinedIngestionPipeline(
            newBatchPipelineBuilder<TestingJoinedIngestionPipelineInput, TestingJoinedIngestionPipelineContext>(),
            joinedPipelineConfig,
            joinedPipelineDeps
        ).build()

        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn(
                {
                    key: `ingestionTestingConsumer.handleEachBatch`,
                    sendException: false,
                },
                async () => await this.handleKafkaBatch(messages)
            )
        })
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        logger.info('🔁', `${this.name} - stopping batch consumer`)
        await this.kafkaConsumer?.disconnect()
        logger.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        if (!this.kafkaConsumer) {
            return new HealthCheckResultError('Kafka consumer not initialized', {})
        }
        return this.kafkaConsumer.isHealthy()
    }

    private runInstrumented<T>(name: string, func: () => Promise<T>): Promise<T> {
        return instrumentFn<T>(`ingestionTestingConsumer.${name}`, func)
    }

    private logBatchStart(messages: Message[]): void {
        const podName = process.env.HOSTNAME || 'unknown'
        const partitionEarliestMessages = new Map<number, Message>()
        const partitionBatchSizes = new Map<number, number>()

        messages.forEach((message) => {
            const existing = partitionEarliestMessages.get(message.partition)
            if (!existing || message.offset < existing.offset) {
                partitionEarliestMessages.set(message.partition, message)
            }
            partitionBatchSizes.set(message.partition, (partitionBatchSizes.get(message.partition) || 0) + 1)
        })

        const partitionData = Array.from(partitionEarliestMessages.entries()).map(([partition, message]) => ({
            partition,
            offset: message.offset,
            batchSize: partitionBatchSizes.get(partition) || 0,
        }))

        logger.info('📖', `KAFKA_BATCH_START: ${this.name}`, {
            pod: podName,
            totalMessages: messages.length,
            partitions: partitionData,
        })
    }

    public async handleKafkaBatch(messages: Message[]): Promise<{ backgroundTask?: Promise<any> }> {
        if (this.config.KAFKA_BATCH_START_LOGGING_ENABLED) {
            this.logBatchStart(messages)
        }

        await this.runIngestionPipeline(messages)

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                    .set(message.timestamp)
            }
        }

        return {
            backgroundTask: this.runInstrumented('awaitScheduledWork', async () => {
                await this.promiseScheduler.waitForAll()
            }),
        }
    }

    private async runIngestionPipeline(messages: Message[]): Promise<void> {
        const batch = messages.map((message) => createOkContext({ message }, { message }))

        this.joinedPipeline.feed(batch)

        // Drain the pipeline
        while ((await this.joinedPipeline.next()) !== null) {
            // Continue until all results are processed
        }
    }
}
