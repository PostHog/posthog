import { Server } from 'http'
import { Message } from 'node-rdkafka'
import express from 'ultimate-express'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../kafka/producer'
import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService } from '../types'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restrictions'
import { logger } from '../utils/logger'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { BatchWritingGroupStore } from '../worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStore } from '../worker/ingestion/persons/batch-writing-person-store'
import { FlushResult, PersonsStore } from '../worker/ingestion/persons/persons-store'
import {
    JoinedIngestionPipelineConfig,
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineInput,
    createJoinedIngestionPipeline,
} from './analytics'
import { deserializeKafkaMessage } from './api/kafka-message-converter'
import { IngestBatchRequest, IngestBatchResponse } from './api/types'
import { IngestionConsumerHub } from './ingestion-consumer'
import { BatchPipeline } from './pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from './pipelines/builders'
import { createContext } from './pipelines/helpers'
import { ok } from './pipelines/results'

export class IngestionApiServer {
    private name = 'ingestion-api-server'
    private app: express.Application
    private httpServer?: Server
    private kafkaProducer?: KafkaProducerWrapper
    private hogTransformer: HogTransformerService
    private personsStore: PersonsStore
    private groupStore: BatchWritingGroupStore
    private eventIngestionRestrictionManager: EventIngestionRestrictionManager
    private readonly promiseScheduler = new PromiseScheduler()
    private started = false

    private joinedPipeline!: BatchPipeline<
        JoinedIngestionPipelineInput,
        void,
        JoinedIngestionPipelineContext,
        JoinedIngestionPipelineContext
    >

    constructor(
        private hub: IngestionConsumerHub,
        private port: number
    ) {
        this.hogTransformer = new HogTransformerService(hub)

        const tokenDistinctIdsToDrop = hub.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
        const tokenDistinctIdsToSkipPersons = hub.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID.split(',').filter(
            (x) => !!x
        )

        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
            pipeline: 'analytics',
            staticDropEventTokens: tokenDistinctIdsToDrop,
            staticSkipPersonTokens: tokenDistinctIdsToSkipPersons,
            staticForceOverflowTokens: [],
        })

        this.personsStore = new BatchWritingPersonsStore(hub.personRepository, hub.kafkaProducer, {
            dbWriteMode: hub.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            useBatchUpdates: hub.PERSON_BATCH_WRITING_USE_BATCH_UPDATES,
            maxConcurrentUpdates: hub.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: hub.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: hub.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
            updateAllProperties: hub.PERSON_PROPERTIES_UPDATE_ALL,
        })

        this.groupStore = new BatchWritingGroupStore(hub, {
            maxConcurrentUpdates: hub.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: hub.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: hub.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })

        this.app = express()
        this.app.use(express.json({ limit: '50mb' }))
        this.app.post('/api/ingestion/batch', (req: express.Request, res: express.Response) =>
            this.handleIngestRequest(req, res)
        )
        this.app.get('/_health', (_req: express.Request, res: express.Response) => {
            const health = this.isHealthy()
            res.status(health.status === 'ok' ? 200 : 503).json({ status: health.status })
        })
        this.app.get('/_ready', (_req: express.Request, res: express.Response) => {
            const ready = this.started
            res.status(ready ? 200 : 503).json({ status: ready ? 'ok' : 'not_ready' })
        })
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    public async start(): Promise<void> {
        await Promise.all([
            this.hogTransformer.start(),
            KafkaProducerWrapper.create(this.hub.KAFKA_CLIENT_RACK).then((producer) => {
                this.kafkaProducer = producer
            }),
        ])

        const pipelineConfig: JoinedIngestionPipelineConfig = {
            hub: this.hub,
            kafkaProducer: this.kafkaProducer!,
            personsStore: this.personsStore,
            hogTransformer: this.hogTransformer,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            overflowEnabled: false,
            overflowTopic: '',
            dlqTopic: this.hub.INGESTION_CONSUMER_DLQ_TOPIC,
            promiseScheduler: this.promiseScheduler,
            perDistinctIdOptions: {
                CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: this.hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: this.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: this.hub.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
                TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: this.hub.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE,
                PIPELINE_STEP_STALLED_LOG_TIMEOUT: this.hub.PIPELINE_STEP_STALLED_LOG_TIMEOUT,
                PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: this.hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
                PERSON_MERGE_ASYNC_ENABLED: this.hub.PERSON_MERGE_ASYNC_ENABLED,
                PERSON_MERGE_ASYNC_TOPIC: this.hub.PERSON_MERGE_ASYNC_TOPIC,
                PERSON_MERGE_SYNC_BATCH_SIZE: this.hub.PERSON_MERGE_SYNC_BATCH_SIZE,
                PERSON_JSONB_SIZE_ESTIMATE_ENABLE: this.hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                PERSON_PROPERTIES_UPDATE_ALL: this.hub.PERSON_PROPERTIES_UPDATE_ALL,
            },
            teamManager: this.hub.teamManager,
            groupTypeManager: this.hub.groupTypeManager,
            groupId: 'ingestion-api',
        }

        this.joinedPipeline = createJoinedIngestionPipeline(
            newBatchPipelineBuilder<JoinedIngestionPipelineInput, JoinedIngestionPipelineContext>(),
            pipelineConfig
        ).build()

        await new Promise<void>((resolve) => {
            this.httpServer = this.app.listen(this.port, () => {
                logger.info('🔌', `Ingestion API server listening on port ${this.port}`)
                resolve()
            })
        })

        this.started = true
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.started = false

        if (this.httpServer) {
            await new Promise<void>((resolve, reject) => {
                this.httpServer!.close((err) => (err ? reject(err) : resolve()))
            })
        }

        await this.kafkaProducer?.disconnect()
        await this.hogTransformer.stop()
        logger.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        if (!this.started) {
            return new HealthCheckResultError('Ingestion API server not started', {})
        }
        return new HealthCheckResultOk()
    }

    private async handleIngestRequest(req: express.Request, res: express.Response): Promise<void> {
        try {
            const body = req.body as IngestBatchRequest

            if (!body.messages || !Array.isArray(body.messages)) {
                const response: IngestBatchResponse = { status: 'error', error: 'messages must be an array' }
                res.status(400).json(response)
                return
            }

            if (body.messages.length === 0) {
                const response: IngestBatchResponse = { status: 'ok', accepted: 0 }
                res.status(200).json(response)
                return
            }

            const messages: Message[] = body.messages.map(deserializeKafkaMessage)
            await this.runPipeline(messages)

            const response: IngestBatchResponse = { status: 'ok', accepted: messages.length }
            res.status(200).json(response)
        } catch (error) {
            logger.error('💥', 'Ingestion API batch processing failed', { error: String(error) })
            const response: IngestBatchResponse = { status: 'error', error: String(error) }
            res.status(500).json(response)
        }
    }

    private async runPipeline(messages: Message[]): Promise<void> {
        const groupStoreForBatch = this.groupStore.forBatch()

        const batch = messages.map((message) => createContext(ok({ message, groupStoreForBatch }), { message }))
        this.joinedPipeline.feed(batch)

        while ((await this.joinedPipeline.next()) !== null) {
            // drain
        }

        const [_, personsStoreMessages] = await Promise.all([groupStoreForBatch.flush(), this.personsStore.flush()])

        if (this.kafkaProducer) {
            await this.producePersonsStoreMessages(personsStoreMessages)
        }

        this.personsStore.reportBatch()
        this.personsStore.reset()
        groupStoreForBatch.reportBatch()

        await Promise.all([this.promiseScheduler.waitForAll(), this.hogTransformer.processInvocationResults()])
    }

    private async producePersonsStoreMessages(personsStoreMessages: FlushResult[]): Promise<void> {
        await Promise.all(
            personsStoreMessages.map((record) =>
                Promise.all(
                    record.topicMessage.messages.map((message) =>
                        this.kafkaProducer!.produce({
                            topic: record.topicMessage.topic,
                            key: message.key ? Buffer.from(message.key) : null,
                            value: message.value ? Buffer.from(message.value) : null,
                            headers: message.headers,
                        })
                    )
                )
            )
        )
        await this.kafkaProducer!.flush()
    }
}
