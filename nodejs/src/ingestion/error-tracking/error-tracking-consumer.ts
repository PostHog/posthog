import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'
import { Message } from 'node-rdkafka'
import { Counter, Gauge } from 'prom-client'

import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PluginEvent } from '~/plugin-scaffold'
import { ErrorTrackingSettingsManager } from '~/utils/error-tracking-settings-manager'

import { TransformationResult } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaConsumerInterface, createKafkaConsumer } from '../../kafka/consumer'
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
    PreCymbalRateLimiterInput,
    createErrorTrackingPipeline,
    runErrorTrackingPipeline,
} from './error-tracking-pipeline'
import { KeyedRateLimiterStepOptions } from './keyed-rate-limiter-step'

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
    rateLimiterEnabled: boolean
    rateLimiterReportingMode: boolean
    rateLimiterRedisHost: string
    rateLimiterRedisPort: number
    rateLimiterRedisTls: boolean
    rateLimiterTtlSeconds: number
    /** Fallback Redis URL when no dedicated host is configured. Required when rateLimiterEnabled. */
    fallbackRedisUrl?: string
    /** Pool sizing for the dedicated rate limiter Redis pool. */
    rateLimiterRedisPoolMinSize?: number
    rateLimiterRedisPoolMaxSize?: number
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
    /** Only required when the rate limiter is enabled; constructed alongside it. */
    errorTrackingSettingsManager?: ErrorTrackingSettingsManager
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
    protected kafkaConsumer: KafkaConsumerInterface
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
    protected rateLimiter?: KeyedRateLimiterService
    protected rateLimiterAppMetricsAggregator?: AppMetricsAggregator
    protected rateLimiterRedis?: RedisV2

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

        // Optional keyed rate limiter — dedicated Redis pool, only built when explicitly enabled.
        // When the master switch is off, no pool/service exists at all (the pipeline step is a no-op).
        if (config.rateLimiterEnabled) {
            const dedicatedHost = config.rateLimiterRedisHost
            this.rateLimiterRedis = createRedisV2PoolFromConfig({
                connection: dedicatedHost
                    ? {
                          url: dedicatedHost,
                          options: {
                              port: config.rateLimiterRedisPort,
                              tls: config.rateLimiterRedisTls ? {} : undefined,
                          },
                          name: 'error-tracking-rate-limiter-redis',
                      }
                    : {
                          url: config.fallbackRedisUrl ?? '',
                          name: 'error-tracking-rate-limiter-redis-fallback',
                      },
                poolMinSize: config.rateLimiterRedisPoolMinSize ?? 1,
                poolMaxSize: config.rateLimiterRedisPoolMaxSize ?? 3,
            })
            this.rateLimiter = new KeyedRateLimiterService(
                {
                    name: 'error-tracking-rate-limiter',
                    // bucketSize/refillRate are intentionally omitted — every request supplies
                    // them via getBucketConfig (per-team), so service-level defaults are unused.
                    ttlSeconds: config.rateLimiterTtlSeconds,
                },
                this.rateLimiterRedis
            )
            this.rateLimiterAppMetricsAggregator = new AppMetricsAggregator(deps.outputs)
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
            preCymbalRateLimiters: this.buildPreCymbalRateLimiterSpecs(),
            errorTrackingSettingsManager: this.rateLimiter ? this.deps.errorTrackingSettingsManager : undefined,
            topHog: this.topHog,
        })

        logger.info('✅', `${this.name} - pipeline initialized`)
    }

    /**
     * Construct the pre-Cymbal rate limiter spec list. Add new specs here as
     * we extend rate limiting beyond the team-global limit (per-hash, per-event-name etc).
     */
    private buildPreCymbalRateLimiterSpecs(): KeyedRateLimiterStepOptions<PreCymbalRateLimiterInput>[] {
        if (!this.rateLimiter) {
            return []
        }

        const specs: KeyedRateLimiterStepOptions<PreCymbalRateLimiterInput>[] = [
            // Team-global cap: every $exception event for a team consumes one token
            // from a per-team bucket.
            {
                rateLimiter: this.rateLimiter,
                appMetricsAggregator: this.rateLimiterAppMetricsAggregator,
                appSource: 'exceptions',
                // Skip rate limiting when the team hasn't opted in (no row or null value).
                // Returning null makes the rate-limiter step pass the input through as `ok()`.
                // The serializer enforces min_value=1, so a non-null value is always positive.
                getKey: (input) =>
                    input.errorTrackingSettings?.projectRateLimitValue == null
                        ? null
                        : `${input.team.id}:exceptions:global`,
                getTeamId: (input) => input.team.id,
                reportingMode: this.config.rateLimiterReportingMode,
                dropReason: 'rate_limited:team_global',
                getBucketConfig: (input) => {
                    // User model: "N events per M minutes".
                    // Token bucket: bucketSize=N (max burst), refillRate=N/(M*60) per second.
                    const settings = input.errorTrackingSettings!
                    const value = settings.projectRateLimitValue!
                    const minutes = settings.projectRateLimitBucketSizeMinutes ?? 60
                    return {
                        bucketSize: value,
                        refillRate: value / (minutes * 60),
                    }
                },
            },
            // TODO: Per-exception-hash limit using a coarse pre-Cymbal fingerprint
            // (Cymbal's proper fingerprint is post-symbolication, so we accept a
            // weaker-but-cheaper bucket here). Wiring would look like:
            // {
            //     rateLimiter: this.rateLimiter,
            //     appMetricsAggregator: this.rateLimiterAppMetricsAggregator,
            //     appSource: 'exceptions',
            //     getKey: (input) => {
            //         const first = input.event.properties?.$exception_list?.[0]
            //         if (!first?.type && !first?.value) return null
            //         const hash = createHash('sha1')
            //             .update(`${first?.type ?? ''}|${first?.value ?? ''}`)
            //             .digest('hex')
            //             .slice(0, 16)
            //         return `${input.team.id}:exceptions:hash:${hash}`
            //     },
            //     getTeamId: (input) => input.team.id,
            //     reportingMode: this.config.rateLimiterReportingMode,
            //     dropReason: 'rate_limited:per_hash',
            //     // getBucketConfig: ... (see TODO above)
            // },
        ]

        return specs
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)

        // Wait for any pending side effects
        await this.promiseScheduler.waitForAll()

        // Drain any pending rate-limiter outcome metrics before output producers go away.
        if (this.rateLimiterAppMetricsAggregator) {
            try {
                await this.rateLimiterAppMetricsAggregator.flush()
            } catch (error) {
                logger.error('⚠️', `${this.name} - failed to flush rate limiter app metrics on stop`, {
                    error: error instanceof Error ? error.message : String(error),
                })
            }
        }

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
            await Promise.all([
                this.promiseScheduler.waitForAll(),
                this.deps.hogTransformer.processInvocationResults(),
                // Best-effort: failures here must not break ingestion.
                this.rateLimiterAppMetricsAggregator?.flush().catch((error) => {
                    logger.error('⚠️', `${this.name} - failed to flush rate limiter app metrics`, {
                        error: error instanceof Error ? error.message : String(error),
                    })
                }),
            ])
        }
    }
}
