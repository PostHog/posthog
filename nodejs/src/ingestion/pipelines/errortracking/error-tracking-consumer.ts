import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'
import { Message } from 'node-rdkafka'
import { Counter, Gauge } from 'prom-client'

import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformationResult } from '~/common/hog-transformations/hog-transformer.interface'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import {
    EventIngestionRestrictionManager,
    EventIngestionRestrictionManagerComponent,
} from '~/common/utils/event-ingestion-restrictions'
import { logger } from '~/common/utils/logger'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { MainLaneOverflowRedirect } from '~/ingestion/common/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from '~/ingestion/common/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from '~/ingestion/common/overflow-redirect/overflow-redis-repository'
import { IngestionLane, IngestionOverflowMode } from '~/ingestion/config'
import { TopHog } from '~/ingestion/framework/tophog'
import { PluginEvent } from '~/plugin-scaffold'
import { HealthCheckResult, PluginServerService } from '~/types'

import { CymbalClient } from './cymbal'
import {
    ErrorTrackingOutputs,
    ErrorTrackingPipeline,
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
    overflowMode: IngestionOverflowMode
    overflowBucketCapacity: number
    overflowBucketReplenishRate: number
    statefulOverflowRedisTTLSeconds: number
    statefulOverflowLocalCacheTTLSeconds: number
    /**
     * When true, overflow redirects keep the original partition key. When
     * false (default), the overflow producer emits with a null key. Applies
     * to both restriction-driven force-overflow and rate-limit-to-overflow.
     */
    preservePartitionLocality: boolean
    pipeline: string
}

/**
 * Interface for the HogTransformer methods used by the error tracking consumer.
 * This allows for easier mocking in tests without needing the full service implementation.
 */
export interface ErrorTrackingHogTransformer {
    start(): Promise<void>
    stop(): Promise<void>
    transformEventAndProduceMessages(event: PluginEvent): Promise<HogTransformationResult>
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
    groupTypeManager: ReadOnlyGroupTypeManager
    cookielessManager: CookielessManager
    redisPool: GenericPool<Redis>
    personRepository: PersonReadRepository
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
    protected kafkaConsumer: KafkaConsumerInterface
    protected pipeline!: ErrorTrackingPipeline
    protected cymbalClient: CymbalClient
    protected promiseScheduler: PromiseScheduler
    private eventIngestionRestrictionManagerComponent: EventIngestionRestrictionManagerComponent
    protected eventIngestionRestrictionManager!: EventIngestionRestrictionManager
    private stopEventIngestionRestrictionManager?: () => Promise<void>
    protected overflowRedirectService?: OverflowRedirectService
    protected overflowLaneTTLRefreshService?: OverflowRedirectService
    protected topHog?: TopHog

    constructor(
        private config: ErrorTrackingConsumerOptions,
        private deps: ErrorTrackingConsumerDeps
    ) {
        this.kafkaConsumer = createKafkaConsumer({
            groupId: config.groupId,
            topic: config.topic,
        })

        this.cymbalClient = new CymbalClient({
            baseUrl: config.cymbalBaseUrl,
            timeoutMs: config.cymbalTimeoutMs,
            maxBodyBytes: config.cymbalMaxBodyBytes,
        })

        this.promiseScheduler = new PromiseScheduler()

        this.eventIngestionRestrictionManagerComponent = new EventIngestionRestrictionManagerComponent(deps.redisPool, {
            pipeline: 'errortracking',
        })

        // Create shared Redis repository for overflow redirect services
        const overflowRedisRepository = new RedisOverflowRepository({
            redisPool: deps.redisPool,
            redisTTLSeconds: config.statefulOverflowRedisTTLSeconds,
        })

        // Create overflow redirect service for main lane (rate limiting)
        if (config.overflowMode === 'redirect') {
            this.overflowRedirectService = new MainLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
                localCacheTTLSeconds: config.statefulOverflowLocalCacheTTLSeconds,
                bucketCapacity: config.overflowBucketCapacity,
                replenishRate: config.overflowBucketReplenishRate,
                overflowType: 'errortracking',
            })
        }

        // Create TTL refresh service for overflow lane
        if (config.overflowMode === 'consume') {
            this.overflowLaneTTLRefreshService = new OverflowLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
                overflowType: 'errortracking',
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
            overflowMode: this.config.overflowMode,
            lane: this.config.lane,
            cymbalUrl: this.config.cymbalBaseUrl,
        })

        const started = await this.eventIngestionRestrictionManagerComponent.start()
        this.eventIngestionRestrictionManager = started.value
        this.stopEventIngestionRestrictionManager = started.stop
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
            promiseScheduler: this.promiseScheduler,
            teamManager: this.deps.teamManager,
            personRepository: this.deps.personRepository,
            hogTransformer: this.deps.hogTransformer,
            cymbalClient: this.cymbalClient,
            groupTypeManager: this.deps.groupTypeManager,
            cookielessManager: this.deps.cookielessManager,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            overflowMode: this.config.overflowMode,
            preservePartitionLocality: this.config.preservePartitionLocality,
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

        await this.stopEventIngestionRestrictionManager?.()

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
