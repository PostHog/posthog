import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'
import { Message } from 'node-rdkafka'
import { Counter, Gauge } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PluginEvent } from '~/plugin-scaffold'

import { TransformationResult } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, IngestionLane, PluginServerService } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { PersonRepository } from '../../worker/ingestion/persons/repositories/person-repository'
import { OverflowOutput } from '../common/outputs'
import { BatchPipelineUnwrapper } from '../pipelines/batch-pipeline-unwrapper'
import { TopHog } from '../tophog'
import { MainLaneOverflowRedirect } from '../utils/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from '../utils/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from '../utils/overflow-redirect/overflow-redis-repository'
import { CymbalClient } from './cymbal'
import {
    ErrorTrackingOutputs,
    ErrorTrackingPipelineOutput,
    createErrorTrackingPipeline,
    runErrorTrackingPipeline,
} from './error-tracking-pipeline'

/**
 * Configuration values for ErrorTrackingConsumer.
 * These are plain values that configure behavior.
 */
export interface ErrorTrackingConsumerOptions {
    groupId: string
    topic: string
    cymbalBaseUrl: string
    cymbalTimeoutMs: number
    cymbalMaxBodyBytes: number
    lane: IngestionLane
    overflowEnabled: boolean
    overflowBucketCapacity: number
    overflowBucketReplenishRate: number
    statefulOverflowEnabled: boolean
    statefulOverflowRedisTTLSeconds: number
    statefulOverflowLocalCacheTTLSeconds: number
    pipeline: string
}

/**
 * Interface for the HogTransformerService methods used by the error tracking consumer.
 * This allows for easier mocking in tests without needing the full service implementation.
 */
export interface ErrorTrackingHogTransformer {
    start(): Promise<void>
    stop(): Promise<void>
    transformEventAndProduceMessages(event: PluginEvent): Promise<TransformationResult>
    processInvocationResults(): Promise<void>
}

/**
 * Dependencies for ErrorTrackingConsumer.
 * These are services and clients that are injected.
 */
export interface ErrorTrackingConsumerDeps {
    outputs: ErrorTrackingOutputs
    teamManager: TeamManager
    hogTransformer: ErrorTrackingHogTransformer
    groupTypeManager: GroupTypeManager
    redisPool: GenericPool<Redis>
    personRepository: PersonRepository
}

// Batch processing status - useful for tracking failures (batch sizes already tracked by KafkaConsumer)
const batchProcessedCounter = new Counter({
    name: 'error_tracking_batches_processed_total',
    help: 'Total batches processed by the error tracking consumer',
    labelNames: ['status'],
})

// Useful for consumer lag calculation
const latestOffsetTimestampGauge = new Gauge({
    name: 'error_tracking_latest_processed_timestamp_ms',
    help: 'Timestamp of the latest offset that has been committed.',
    labelNames: ['topic', 'partition', 'groupId'],
    aggregator: 'max',
})

export class ErrorTrackingConsumer {
    protected name = 'error-tracking-consumer'
    protected kafkaConsumer: KafkaConsumer
    protected pipeline!: BatchPipelineUnwrapper<
        { message: Message },
        ErrorTrackingPipelineOutput,
        { message: Message },
        OverflowOutput
    >
    protected cymbalClient: CymbalClient
    protected promiseScheduler: PromiseScheduler
    protected eventIngestionRestrictionManager: EventIngestionRestrictionManager
    protected overflowRedirectService?: OverflowRedirectService
    protected overflowLaneTTLRefreshService?: OverflowRedirectService
    protected topHog?: TopHog

    constructor(
        private config: ErrorTrackingConsumerOptions,
        private deps: ErrorTrackingConsumerDeps
    ) {
        this.kafkaConsumer = new KafkaConsumer({
            groupId: config.groupId,
            topic: config.topic,
        })

        this.cymbalClient = new CymbalClient({
            baseUrl: config.cymbalBaseUrl,
            timeoutMs: config.cymbalTimeoutMs,
            maxBodyBytes: config.cymbalMaxBodyBytes,
        })

        this.promiseScheduler = new PromiseScheduler()

        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(deps.redisPool, {
            pipeline: 'error_tracking',
        })

        // Create shared Redis repository for overflow redirect services
        const overflowRedisRepository = new RedisOverflowRepository({
            redisPool: deps.redisPool,
            redisTTLSeconds: config.statefulOverflowRedisTTLSeconds,
        })

        // Create overflow redirect service for main lane (rate limiting)
        if (config.overflowEnabled && config.lane === 'main') {
            this.overflowRedirectService = new MainLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
                localCacheTTLSeconds: config.statefulOverflowLocalCacheTTLSeconds,
                bucketCapacity: config.overflowBucketCapacity,
                replenishRate: config.overflowBucketReplenishRate,
                statefulEnabled: config.statefulOverflowEnabled,
            })
        }

        // Create TTL refresh service for overflow lane
        if (config.lane === 'overflow' && config.statefulOverflowEnabled) {
            this.overflowLaneTTLRefreshService = new OverflowLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
            })
        }
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    public async start(): Promise<void> {
        logger.info('🚀', `${this.name} - starting`, {
            groupId: this.config.groupId,
            topic: this.config.topic,
            overflowEnabled: this.config.overflowEnabled,
            lane: this.config.lane,
            statefulOverflowEnabled: this.config.statefulOverflowEnabled,
            cymbalUrl: this.config.cymbalBaseUrl,
        })

        // Initialize pipeline with dependencies
        await this.initializePipeline()

        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn('errorTrackingConsumer.handleEachBatch', async () => {
                await this.handleKafkaBatch(messages)
            })
        })

        logger.info('✅', `${this.name} - started`)
    }

    private async initializePipeline(): Promise<void> {
        // Start the Hog transformer service
        await this.deps.hogTransformer.start()

        // Initialize TopHog for metrics
        this.topHog = new TopHog({
            outputs: this.deps.outputs,
            pipeline: this.config.pipeline,
            lane: this.config.lane,
        })
        this.topHog.start()

        this.pipeline = createErrorTrackingPipeline({
            outputs: this.deps.outputs,
            groupId: this.config.groupId,
            promiseScheduler: this.promiseScheduler,
            teamManager: this.deps.teamManager,
            personRepository: this.deps.personRepository,
            hogTransformer: this.deps.hogTransformer,
            cymbalClient: this.cymbalClient,
            groupTypeManager: this.deps.groupTypeManager,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            overflowEnabled: this.config.overflowEnabled,
            overflowRedirectService: this.overflowRedirectService,
            overflowLaneTTLRefreshService: this.overflowLaneTTLRefreshService,
            topHog: this.topHog,
        })

        logger.info('✅', `${this.name} - pipeline initialized`)
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)

        // Wait for any pending side effects
        await this.promiseScheduler.waitForAll()

        // Shutdown overflow services
        await this.overflowRedirectService?.shutdown()
        await this.overflowLaneTTLRefreshService?.shutdown()

        // Stop Hog transformer service
        await this.deps.hogTransformer.stop()

        // Stop TopHog metrics
        await this.topHog?.stop()

        await this.kafkaConsumer.disconnect()

        logger.info('👍', `${this.name} - stopped`)
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }

    public async handleKafkaBatch(messages: Message[]): Promise<void> {
        // Update offset timestamps for lag metrics
        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.config.groupId })
                    .set(message.timestamp)
            }
        }

        try {
            await runErrorTrackingPipeline(this.pipeline, messages)
            batchProcessedCounter.inc({ status: 'success' })
        } catch (error) {
            batchProcessedCounter.inc({ status: 'error' })
            logger.error('❌', `${this.name} - batch processing failed`, {
                error: error instanceof Error ? error.message : String(error),
                size: messages.length,
            })
            throw error
        } finally {
            // Flush scheduled work and invocation results to prevent memory accumulation
            await Promise.all([this.promiseScheduler.waitForAll(), this.deps.hogTransformer.processInvocationResults()])
        }
    }
}
