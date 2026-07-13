import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'
import { Message } from 'node-rdkafka'
import { Counter, Gauge } from 'prom-client'

import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformationResult } from '~/common/hog-transformations/hog-transformer.interface'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { OverflowOutput } from '~/common/outputs'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { ErrorTrackingSettingsManager } from '~/common/utils/error-tracking-settings-manager'
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
import { IngestionLane } from '~/ingestion/config'
import { BatchPipelineUnwrapper } from '~/ingestion/framework/batch-pipeline-unwrapper'
import { TopHog } from '~/ingestion/framework/tophog'
import { PluginEvent } from '~/plugin-scaffold'
import { HealthCheckResult, PluginServerService } from '~/types'

import { CymbalClient } from './cymbal'
import {
    ErrorTrackingOutputs,
    ErrorTrackingPipelineOutput,
    PostCymbalRateLimiterInput,
    createErrorTrackingPipeline,
    runErrorTrackingPipeline,
} from './error-tracking-pipeline'
import { KeyedRateLimiterStepOptions } from './keyed-rate-limiter-step'
import { PerIssueGuardedRateLimiterService } from './per-issue-guarded-rate-limiter.service'

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
    /**
     * When true, overflow redirects keep the original partition key. When
     * false (default), the overflow producer emits with a null key. Applies
     * to both restriction-driven force-overflow and rate-limit-to-overflow.
     */
    preservePartitionLocality: boolean
    pipeline: string
    rateLimiterEnabled: boolean
    rateLimiterReportingMode: boolean
    rateLimiterRedisHost: string
    rateLimiterRedisPort: number
    rateLimiterRedisTls: boolean
    rateLimiterTtlSeconds: number
    perIssueGuardThreshold: number
    perIssueGuardWindowTtlSeconds: number
    perIssueGuardCooldownTtlSeconds: number
    /** Fallback Redis URL when no dedicated host is configured. Required when rateLimiterEnabled. */
    fallbackRedisUrl?: string
    /** Pool sizing for the dedicated rate limiter Redis pool. */
    rateLimiterRedisPoolMinSize?: number
    rateLimiterRedisPoolMaxSize?: number
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
    /** Only required when the rate limiter is enabled; constructed alongside it. */
    errorTrackingSettingsManager?: ErrorTrackingSettingsManager
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
    protected pipeline!: BatchPipelineUnwrapper<
        { message: Message },
        ErrorTrackingPipelineOutput,
        { message: Message },
        OverflowOutput
    >
    protected cymbalClient: CymbalClient
    protected promiseScheduler: PromiseScheduler
    private eventIngestionRestrictionManagerComponent: EventIngestionRestrictionManagerComponent
    protected eventIngestionRestrictionManager!: EventIngestionRestrictionManager
    private stopEventIngestionRestrictionManager?: () => Promise<void>
    protected overflowRedirectService?: OverflowRedirectService
    protected overflowLaneTTLRefreshService?: OverflowRedirectService
    protected topHog?: TopHog
    protected rateLimiter?: KeyedRateLimiterService
    protected perIssueGuardedRateLimiter?: PerIssueGuardedRateLimiterService
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

        this.eventIngestionRestrictionManagerComponent = new EventIngestionRestrictionManagerComponent(deps.redisPool, {
            pipeline: 'errortracking',
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
                overflowType: 'errortracking',
            })
        }

        // Create TTL refresh service for overflow lane
        if (config.lane === 'overflow' && config.statefulOverflowEnabled) {
            this.overflowLaneTTLRefreshService = new OverflowLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
                overflowType: 'errortracking',
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
            this.perIssueGuardedRateLimiter = new PerIssueGuardedRateLimiterService(
                {
                    name: 'error-tracking-rate-limiter',
                    threshold: config.perIssueGuardThreshold,
                    windowTtlSeconds: config.perIssueGuardWindowTtlSeconds,
                    cooldownTtlSeconds: config.perIssueGuardCooldownTtlSeconds,
                    bucketTtlSeconds: config.rateLimiterTtlSeconds,
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
            overflowEnabled: this.config.overflowEnabled,
            preservePartitionLocality: this.config.preservePartitionLocality,
            overflowRedirectService: this.overflowRedirectService,
            overflowLaneTTLRefreshService: this.overflowLaneTTLRefreshService,
            postCymbalRateLimiters: this.buildPostCymbalRateLimiterSpecs(),
            errorTrackingSettingsManager: this.rateLimiter ? this.deps.errorTrackingSettingsManager : undefined,
            topHog: this.topHog,
        })

        logger.info('✅', `${this.name} - pipeline initialized`)
    }

    /** Per-issue spec uses the guarded service; team-global spec uses the base service. */
    private buildPostCymbalRateLimiterSpecs(): KeyedRateLimiterStepOptions<PostCymbalRateLimiterInput>[] {
        if (!this.rateLimiter || !this.perIssueGuardedRateLimiter) {
            return []
        }

        return [
            // Per-issue cap runs before the team-global cap so a runaway issue
            // gets dropped against its own bucket instead of draining the
            // team-global budget on its way out.
            {
                rateLimiter: this.perIssueGuardedRateLimiter,
                appMetricsAggregator: this.rateLimiterAppMetricsAggregator,
                appSource: 'exceptions',
                getKey: (input) => {
                    if (input.errorTrackingSettings?.perIssueRateLimitValue == null) {
                        return null
                    }
                    const issueId = input.event.properties?.$exception_issue_id
                    return typeof issueId === 'string' && issueId
                        ? `${input.team.id}:exceptions:issue:${issueId}`
                        : null
                },
                // Record the allowed/rate_limited decision per issue so the per-issue view can
                // show counts keyed by the Cymbal-assigned issue id. getAppSourceId is only called
                // for inputs whose getKey was non-null, which guarantees $exception_issue_id is a
                // non-empty string here.
                getAppSourceId: (input) => input.event.properties?.$exception_issue_id as string,
                getTeamId: (input) => input.team.id,
                reportingMode: this.config.rateLimiterReportingMode,
                dropReason: 'rate_limited:per_issue',
                getBucketConfig: (input) => {
                    const settings = input.errorTrackingSettings!
                    const value = settings.perIssueRateLimitValue!
                    const minutes = settings.perIssueRateLimitBucketSizeMinutes ?? 60
                    return {
                        bucketSize: value,
                        refillRate: value / (minutes * 60),
                    }
                },
            },
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
        ]
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
