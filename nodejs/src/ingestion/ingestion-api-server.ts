import * as grpc from '@grpc/grpc-js'
import * as protoLoader from '@grpc/proto-loader'
import { Server as HttpServer } from 'http'
import { Message } from 'node-rdkafka'
import path from 'path'
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
import { IngestBatchResponse, ProtoKafkaMessage } from './api/types'
import { IngestionConsumerHub } from './ingestion-consumer'
import { BatchPipeline } from './pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from './pipelines/builders'
import { createContext } from './pipelines/helpers'
import { ok } from './pipelines/results'

const HEALTH_CHECK_PORT_OFFSET = 100

export class IngestionApiServer {
    private name = 'ingestion-api-server'
    private grpcServer?: grpc.Server
    private healthHttpServer?: HttpServer
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

        // Start gRPC server on main port
        await this.startGrpcServer()

        // Start HTTP health check on offset port
        await this.startHealthServer()

        this.started = true
    }

    private async startGrpcServer(): Promise<void> {
        const protoPath = path.resolve(__dirname, '../../../proto/ingestion/v1/ingestion.proto')
        const packageDef = protoLoader.loadSync(protoPath, {
            keepCase: true,
            longs: Number,
            defaults: true,
            oneofs: true,
        })
        const proto = grpc.loadPackageDefinition(packageDef) as any

        this.grpcServer = new grpc.Server()
        this.grpcServer.addService(proto.ingestion.v1.IngestionService.service, {
            IngestBatch: (call: grpc.ServerUnaryCall<any, any>, callback: grpc.sendUnaryData<IngestBatchResponse>) => {
                const messages: ProtoKafkaMessage[] = call.request.messages
                this.handleIngestBatch(messages)
                    .then((count) => callback(null, { status: 0, accepted: count, error: '' }))
                    .catch((err) => callback(null, { status: 1, accepted: 0, error: String(err) }))
            },
        })

        await new Promise<void>((resolve, reject) => {
            this.grpcServer!.bindAsync(`0.0.0.0:${this.port}`, grpc.ServerCredentials.createInsecure(), (err) => {
                if (err) {
                    reject(err)
                    return
                }
                logger.info('gRPC', `Ingestion API gRPC server listening on port ${this.port}`)
                resolve()
            })
        })
    }

    private async startHealthServer(): Promise<void> {
        const healthPort = this.port + HEALTH_CHECK_PORT_OFFSET
        const app = express()
        app.get('/_health', (_req: express.Request, res: express.Response) => {
            const health = this.isHealthy()
            res.status(health.status === 'ok' ? 200 : 503).json({ status: health.status })
        })
        app.get('/_ready', (_req: express.Request, res: express.Response) => {
            const ready = this.started
            res.status(ready ? 200 : 503).json({ status: ready ? 'ok' : 'not_ready' })
        })

        await new Promise<void>((resolve) => {
            this.healthHttpServer = app.listen(healthPort, () => {
                logger.info('HTTP', `Health check server listening on port ${healthPort}`)
                resolve()
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('stop', `${this.name} - stopping`)
        this.started = false

        if (this.grpcServer) {
            await new Promise<void>((resolve) => {
                this.grpcServer!.tryShutdown(() => resolve())
            })
        }

        if (this.healthHttpServer) {
            await new Promise<void>((resolve, reject) => {
                this.healthHttpServer!.close((err) => (err ? reject(err) : resolve()))
            })
        }

        await this.kafkaProducer?.disconnect()
        await this.hogTransformer.stop()
        logger.info('stop', `${this.name} - stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        if (!this.started) {
            return new HealthCheckResultError('Ingestion API server not started', {})
        }
        return new HealthCheckResultOk()
    }

    private async handleIngestBatch(protoMessages: ProtoKafkaMessage[]): Promise<number> {
        if (!protoMessages || protoMessages.length === 0) {
            return 0
        }

        logger.info('batch', `Ingestion API received batch of ${protoMessages.length} messages`)

        const messages: Message[] = protoMessages.map(deserializeKafkaMessage)
        await this.runPipeline(messages)

        logger.info('batch', `Ingestion API processed batch of ${messages.length} messages`)
        return messages.length
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
