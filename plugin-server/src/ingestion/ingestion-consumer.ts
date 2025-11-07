import { Message } from 'node-rdkafka'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { MessageSizeTooLarge } from '~/utils/db/error'
import { captureIngestionWarning } from '~/worker/ingestion/utils'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { KafkaConsumer } from '../kafka/consumer'
import { KafkaProducerWrapper } from '../kafka/producer'
import { latestOffsetTimestampGauge } from '../main/ingestion-queues/metrics'
import {
    HealthCheckResult,
    HealthCheckResultError,
    Hub,
    IncomingEventWithTeam,
    PluginServerService,
    PluginsServerConfig,
    Team,
} from '../types'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restriction-manager'
import { logger } from '../utils/logger'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { BatchWritingGroupStore } from '../worker/ingestion/groups/batch-writing-group-store'
import { GroupStoreForBatch } from '../worker/ingestion/groups/group-store-for-batch.interface'
import { BatchWritingPersonsStore } from '../worker/ingestion/persons/batch-writing-person-store'
import { FlushResult, PersonsStoreForBatch } from '../worker/ingestion/persons/persons-store-for-batch'
import {
    createApplyCookielessProcessingStep,
    createApplyDropRestrictionsStep,
    createApplyForceOverflowRestrictionsStep,
    createApplyPersonProcessingRestrictionsStep,
    createDropExceptionEventsStep,
    createMaybeRedirectToTestingTopicStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createRateLimitToOverflowStep,
    createResolveTeamStep,
    createValidateEventPropertiesStep,
    createValidateEventUuidStep,
} from './event-preprocessing'
import { createCreateEventStep } from './event-processing/create-event-step'
import { createDisablePersonProcessingStep } from './event-processing/disable-person-processing-step'
import { createEmitEventStep } from './event-processing/emit-event-step'
import { createEventPipelineRunnerHeatmapStep } from './event-processing/event-pipeline-runner-heatmap-step'
import { createEventPipelineRunnerV1Step } from './event-processing/event-pipeline-runner-v1-step'
import { createExtractHeatmapDataStep } from './event-processing/extract-heatmap-data-step'
import { createHandleClientIngestionWarningStep } from './event-processing/handle-client-ingestion-warning-step'
import { createNormalizeEventStep } from './event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from './event-processing/normalize-process-person-flag-step'
import { createPrefetchHogFunctionsStep } from './event-processing/prefetch-hog-functions-step'
import { createSkipEmitEventStep } from './event-processing/skip-emit-event-step'
import { createTrackNonPersonEventUpdatesStep } from './event-processing/track-non-person-event-updates-step'
import { BatchPipelineUnwrapper } from './pipelines/batch-pipeline-unwrapper'
import { BatchPipeline } from './pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from './pipelines/builders'
import { createBatch, createUnwrapper } from './pipelines/helpers'
import { PipelineConfig } from './pipelines/result-handling-pipeline'
import { MemoryRateLimiter } from './utils/overflow-detector'

export interface PerDistinctIdPipelineInput extends IncomingEventWithTeam {
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
}

export class IngestionConsumer {
    protected name = 'ingestion-consumer'
    protected groupId: string
    protected topic: string
    protected dlqTopic: string
    protected overflowTopic?: string
    protected testingTopic?: string
    protected kafkaConsumer: KafkaConsumer
    isStopping = false
    protected kafkaProducer?: KafkaProducerWrapper
    protected kafkaOverflowProducer?: KafkaProducerWrapper
    public hogTransformer: HogTransformerService
    private overflowRateLimiter: MemoryRateLimiter
    private ingestionWarningLimiter: MemoryRateLimiter
    private tokenDistinctIdsToDrop: string[] = []
    private tokenDistinctIdsToSkipPersons: string[] = []
    private tokenDistinctIdsToForceOverflow: string[] = []
    private personStore: BatchWritingPersonsStore
    public groupStore: BatchWritingGroupStore
    private eventIngestionRestrictionManager: EventIngestionRestrictionManager
    public readonly promiseScheduler = new PromiseScheduler()

    private pipeline!: BatchPipelineUnwrapper<
        { message: Message; personsStoreForBatch: PersonsStoreForBatch; groupStoreForBatch: GroupStoreForBatch },
        void,
        { message: Message }
    >
    private perDistinctIdPipeline!: BatchPipeline<PerDistinctIdPipelineInput, void, { message: Message; team: Team }>

    constructor(
        private hub: Hub,
        overrides: Partial<
            Pick<
                PluginsServerConfig,
                | 'INGESTION_CONSUMER_GROUP_ID'
                | 'INGESTION_CONSUMER_CONSUME_TOPIC'
                | 'INGESTION_CONSUMER_OVERFLOW_TOPIC'
                | 'INGESTION_CONSUMER_DLQ_TOPIC'
                | 'INGESTION_CONSUMER_TESTING_TOPIC'
            >
        > = {}
    ) {
        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = overrides.INGESTION_CONSUMER_GROUP_ID ?? hub.INGESTION_CONSUMER_GROUP_ID
        this.topic = overrides.INGESTION_CONSUMER_CONSUME_TOPIC ?? hub.INGESTION_CONSUMER_CONSUME_TOPIC
        this.overflowTopic = overrides.INGESTION_CONSUMER_OVERFLOW_TOPIC ?? hub.INGESTION_CONSUMER_OVERFLOW_TOPIC
        this.dlqTopic = overrides.INGESTION_CONSUMER_DLQ_TOPIC ?? hub.INGESTION_CONSUMER_DLQ_TOPIC
        this.tokenDistinctIdsToDrop = hub.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
        this.tokenDistinctIdsToSkipPersons = hub.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID.split(',').filter(
            (x) => !!x
        )
        this.tokenDistinctIdsToForceOverflow = hub.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID.split(',').filter(
            (x) => !!x
        )
        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
            pipeline: 'analytics',
            staticDropEventTokens: this.tokenDistinctIdsToDrop,
            staticSkipPersonTokens: this.tokenDistinctIdsToSkipPersons,
            staticForceOverflowTokens: this.tokenDistinctIdsToForceOverflow,
        })
        this.testingTopic = overrides.INGESTION_CONSUMER_TESTING_TOPIC ?? hub.INGESTION_CONSUMER_TESTING_TOPIC

        this.name = `ingestion-consumer-${this.topic}`
        this.overflowRateLimiter = new MemoryRateLimiter(
            this.hub.EVENT_OVERFLOW_BUCKET_CAPACITY,
            this.hub.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE
        )

        this.ingestionWarningLimiter = new MemoryRateLimiter(1, 1.0 / 3600)
        this.hogTransformer = new HogTransformerService(hub)

        this.personStore = new BatchWritingPersonsStore(this.hub.personRepository, this.hub.db.kafkaProducer, {
            dbWriteMode: this.hub.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            maxConcurrentUpdates: this.hub.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.hub.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.hub.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })

        this.groupStore = new BatchWritingGroupStore(this.hub, {
            maxConcurrentUpdates: this.hub.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.hub.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.hub.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })

        this.kafkaConsumer = new KafkaConsumer({
            groupId: this.groupId,
            topic: this.topic,
        })
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    public async start(): Promise<void> {
        await Promise.all([
            this.hogTransformer.start(),
            KafkaProducerWrapper.create(this.hub).then((producer) => {
                this.kafkaProducer = producer
            }),
            // TRICKY: When we produce overflow events they are back to the kafka we are consuming from
            KafkaProducerWrapper.create(this.hub, 'CONSUMER').then((producer) => {
                this.kafkaOverflowProducer = producer
            }),
        ])

        // Initialize batch preprocessing pipeline after kafka producer is available
        this.initializePipeline()

        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn(
                {
                    key: `ingestionConsumer.handleEachBatch`,
                    sendException: false,
                },
                async () => await this.handleKafkaBatch(messages)
            )
        })
    }

    private initializePipeline(): void {
        const pipelineConfig: PipelineConfig = {
            kafkaProducer: this.kafkaProducer!,
            dlqTopic: this.dlqTopic,
            promiseScheduler: this.promiseScheduler,
        }

        const pipeline = newBatchPipelineBuilder<
            { message: Message; personsStoreForBatch: PersonsStoreForBatch; groupStoreForBatch: GroupStoreForBatch },
            { message: Message }
        >()
            .messageAware((builder) =>
                // All of these steps are synchronous, so we can process the messages sequentially
                // to avoid buffering due to reordering.
                builder.sequentially((b) =>
                    b
                        .pipe(createParseHeadersStep())
                        .pipe(createMaybeRedirectToTestingTopicStep(this.testingTopic ?? null))
                        .pipe(createApplyDropRestrictionsStep(this.eventIngestionRestrictionManager))
                        .pipe(
                            createApplyForceOverflowRestrictionsStep(this.eventIngestionRestrictionManager, {
                                overflowEnabled: this.overflowEnabled(),
                                overflowTopic: this.overflowTopic || '',
                                preservePartitionLocality: this.hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                            })
                        )
                        .pipe(createParseKafkaMessageStep())
                        .pipe(createDropExceptionEventsStep())
                        .pipe(createResolveTeamStep(this.hub))
                )
            )
            // We want to handle the first batch of rejected events, so that the remaining ones
            // can be processed in the team context.
            .handleResults(pipelineConfig)
            // We don't need to block the pipeline with side effects at this stage.
            .handleSideEffects(this.promiseScheduler, { await: false })
            // This is the first synchronization point, where we gather all events.
            // We need to gather here because the pipeline consumer only calls next once.
            // Once we transition to a continuous consumer, we can remove this gather.
            .gather()
            .filterOk()
            // Now we know all messages are in the team context.
            .map((element) => ({
                result: element.result,
                context: {
                    ...element.context,
                    team: element.result.value.team,
                },
            }))
            .messageAware((builder) =>
                builder
                    .teamAware((b) =>
                        // These steps are also synchronous, so we can process events sequentially.
                        b
                            .sequentially((c) =>
                                c
                                    .pipe(createValidateEventPropertiesStep())
                                    .pipe(
                                        createApplyPersonProcessingRestrictionsStep(
                                            this.eventIngestionRestrictionManager
                                        )
                                    )
                                    .pipe(createValidateEventUuidStep())
                            )
                            // We want to call cookieless with the whole batch at once.
                            .gather()
                            .pipeBatch(createApplyCookielessProcessingStep(this.hub))
                            .pipeBatch(
                                createRateLimitToOverflowStep(
                                    this.overflowRateLimiter,
                                    this.overflowEnabled(),
                                    this.overflowTopic || '',
                                    this.hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY
                                )
                            )
                    )
                    .handleIngestionWarnings(this.kafkaProducer!)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(this.promiseScheduler, { await: false })
            // We synchronize once again to ensure we return all events in one batch.
            .gather()
            // Shard events by distinct_id to ensure ordering guarantees per distinct_id
            .sharding(
                (resultWithContext) => {
                    const event = resultWithContext.result.value.event
                    const token = event.token ?? ''
                    const distinctId = event.distinct_id ?? ''
                    // Hash by token:distinct_id to ensure all events for same distinct_id go to same shard
                    return this.hashString(`${token}:${distinctId}`)
                },
                this.hub.INGESTION_CONCURRENCY,
                (builder) =>
                    builder
                        .messageAware((b) =>
                            b
                                .teamAware((team) =>
                                    team
                                        .pipeBatch(createPrefetchHogFunctionsStep(this.hub, this.hogTransformer))
                                        .pipeBatch(createTrackNonPersonEventUpdatesStep())
                                        // We process the events for the distinct id sequentially to provide ordering guarantees.
                                        .sequentially((seq) =>
                                            seq.retry(
                                                (retry) =>
                                                    retry.branching<
                                                        'client_ingestion_warning' | 'heatmap' | 'event',
                                                        void
                                                    >(
                                                        (input) => {
                                                            switch (input.event.event) {
                                                                case '$$client_ingestion_warning':
                                                                    return 'client_ingestion_warning'
                                                                case '$$heatmap':
                                                                    return 'heatmap'
                                                                default:
                                                                    return 'event'
                                                            }
                                                        },
                                                        (branches) => {
                                                            branches
                                                                .branch('client_ingestion_warning', (br) =>
                                                                    br.pipe(createHandleClientIngestionWarningStep())
                                                                )
                                                                .branch('heatmap', (br) =>
                                                                    br
                                                                        .pipe(createDisablePersonProcessingStep())
                                                                        .pipe(createNormalizeEventStep(this.hub))
                                                                        .pipe(
                                                                            createEventPipelineRunnerHeatmapStep(
                                                                                this.hub,
                                                                                this.hogTransformer
                                                                            )
                                                                        )
                                                                        .pipe(
                                                                            createExtractHeatmapDataStep({
                                                                                kafkaProducer: this.kafkaProducer!,
                                                                                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC:
                                                                                    this.hub
                                                                                        .CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                                                                            })
                                                                        )
                                                                        .pipe(createSkipEmitEventStep())
                                                                )
                                                                .branch('event', (br) =>
                                                                    br
                                                                        .pipe(createNormalizeProcessPersonFlagStep())
                                                                        .pipe(
                                                                            createEventPipelineRunnerV1Step(
                                                                                this.hub,
                                                                                this.hogTransformer
                                                                            )
                                                                        )
                                                                        // TRICKY: Older client versions may still send $heatmap_data as properties on regular events.
                                                                        // This step extracts and processes that data even though up-to-date clients send dedicated $$heatmap events.
                                                                        // TODO: Verify if we still receive $heatmap_data on regular events and consider removing this step if not.
                                                                        .pipe(
                                                                            createExtractHeatmapDataStep({
                                                                                kafkaProducer: this.kafkaProducer!,
                                                                                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC:
                                                                                    this.hub
                                                                                        .CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                                                                            })
                                                                        )
                                                                        .pipe(createCreateEventStep())
                                                                        .pipe(
                                                                            createEmitEventStep({
                                                                                kafkaProducer: this.kafkaProducer!,
                                                                                clickhouseJsonEventsTopic:
                                                                                    this.hub
                                                                                        .CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                                                                            })
                                                                        )
                                                                )
                                                        }
                                                    ),
                                                {
                                                    tries: 3,
                                                    sleepMs: 100,
                                                }
                                            )
                                        )
                                )
                                .handleIngestionWarnings(this.kafkaProducer!)
                        )
                        .handleResults(pipelineConfig)
                        .handleSideEffects(this.promiseScheduler, { await: false })
                        .gather()
            )
            .build()

        this.pipeline = createUnwrapper(pipeline)
    }

    private hashString(str: string): number {
        let hash = 0
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i)
            hash = (hash << 5) - hash + char
            hash = hash & hash // Convert to 32bit integer
        }
        return Math.abs(hash)
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        logger.info('🔁', `${this.name} - stopping batch consumer`)
        await this.kafkaConsumer?.disconnect()
        logger.info('🔁', `${this.name} - stopping kafka producer`)
        await this.kafkaProducer?.disconnect()
        logger.info('🔁', `${this.name} - stopping kafka overflow producer`)
        await this.kafkaOverflowProducer?.disconnect()
        logger.info('🔁', `${this.name} - stopping hog transformer`)
        await this.hogTransformer.stop()
        logger.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        if (!this.kafkaConsumer) {
            return new HealthCheckResultError('Kafka consumer not initialized', {})
        }
        return this.kafkaConsumer.isHealthy()
    }

    private runInstrumented<T>(name: string, func: () => Promise<T>): Promise<T> {
        return instrumentFn<T>(`ingestionConsumer.${name}`, func)
    }

    private logBatchStart(messages: Message[]): void {
        // Log earliest message from each partition to detect duplicate processing across pods
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

        // Create partition data array for single log entry
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
        if (this.hub.KAFKA_BATCH_START_LOGGING_ENABLED) {
            this.logBatchStart(messages)
        }

        const personsStoreForBatch = this.personStore.forBatch()
        const groupStoreForBatch = this.groupStore.forBatch()

        await this.runInstrumented('processEvents', () =>
            this.processEvents(messages, personsStoreForBatch, groupStoreForBatch)
        )

        const [_, personsStoreMessages] = await Promise.all([groupStoreForBatch.flush(), personsStoreForBatch.flush()])

        if (this.kafkaProducer) {
            await this.producePersonsStoreMessages(personsStoreMessages)
        }

        personsStoreForBatch.reportBatch()
        groupStoreForBatch.reportBatch()

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                    .set(message.timestamp)
            }
        }

        return {
            backgroundTask: this.runInstrumented('awaitScheduledWork', async () => {
                await Promise.all([this.promiseScheduler.waitForAll(), this.hogTransformer.processInvocationResults()])
            }),
        }
    }

    private async producePersonsStoreMessages(personsStoreMessages: FlushResult[]): Promise<void> {
        await Promise.all(
            personsStoreMessages.map((record) => {
                return Promise.all(
                    record.topicMessage.messages.map(async (message) => {
                        try {
                            return await this.kafkaProducer!.produce({
                                topic: record.topicMessage.topic,
                                key: message.key ? Buffer.from(message.key) : null,
                                value: message.value ? Buffer.from(message.value) : null,
                                headers: message.headers,
                            })
                        } catch (error) {
                            if (error instanceof MessageSizeTooLarge) {
                                await captureIngestionWarning(
                                    this.kafkaProducer!,
                                    record.teamId,
                                    'message_size_too_large',
                                    {
                                        eventUuid: record.uuid,
                                        distinctId: record.distinctId,
                                    }
                                )
                                logger.warn('🪣', `Message size too large`, {
                                    topic: record.topicMessage.topic,
                                    key: message.key,
                                    headers: message.headers,
                                })
                            } else {
                                throw error
                            }
                        }
                    })
                )
            })
        )
        await this.kafkaProducer!.flush()
    }

    private async processEvents(
        messages: Message[],
        personsStoreForBatch: PersonsStoreForBatch,
        groupStoreForBatch: GroupStoreForBatch
    ): Promise<void> {
        // Create batch using the helper function
        const batch = createBatch(messages.map((message) => ({ message, personsStoreForBatch, groupStoreForBatch })))

        // Feed batch to the pipeline
        this.pipeline.feed(batch)

        // Process all events through the pipeline
        let result = await this.pipeline.next()
        while (result !== null) {
            result = await this.pipeline.next()
        }
    }

    private overflowEnabled(): boolean {
        return (
            !!this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
            this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC !== this.topic &&
            !this.testingTopic
        )
    }
}
