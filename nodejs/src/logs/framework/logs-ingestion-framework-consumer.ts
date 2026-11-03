import { Message } from 'node-rdkafka'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { QuotaResource } from '~/common/services/quota-limiting.service'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import type { LogsSettings } from '~/types'
import { HealthCheckResult, PluginServerService } from '~/types'

import { LogsIngestionConsumerConfig } from '../config'
import { InternalLogsVerifier } from '../internal-logs'
import {
    DEFAULT_LOGS_RETENTION_DAYS,
    LogsIngestionConsumerDeps,
    UsageStatsByTeam,
    describeBatchPosition,
} from '../logs-ingestion-consumer'
import type { MetricRuleSource } from '../metrics-rules/compile-metric-rules'
import { MetricSeriesAdmission } from '../metrics-rules/tally'
import type { RetentionRuleSource } from '../retention/compile-retention-rules'
import { LogsSamplingService } from '../sampling/logs-sampling.service'
import { LogsRateLimiterService } from '../services/logs-rate-limiter.service'
import type { TransformationBatchBudget } from '../transformations/logs-transformer.service'
import { LogsIngestionMessage } from '../types'
import { LogsAdmissionInput, LogsBatchUsage, reportDroppedUsage } from './admission-steps'
import { emitMetricRuleTallies, emitUsageMetrics, queueInternalLogsUsage } from './finalize-logs-batch'
import {
    LogsConsumerIdentity,
    LogsFeatureGates,
    LogsPipelineContext,
    LogsUsageMetricsQueue,
    isUnbilledInternal,
} from './logs-pipeline-context'
import {
    createLogsAdmissionPipeline,
    createLogsParsePipeline,
    createLogsProcessingPipeline,
    runChunkPipeline,
} from './logs-pipelines'
import { type LogsProcessingPass, type MetricTalliesByTeam } from './process-log-message-step'

/**
 * Kafka entrypoint for logs ingestion on the ingestion framework, with the same public API as
 * `LogsIngestionConsumer`. The work runs in three pipelines (see `logs-pipelines.ts`): parse and
 * admission run before the batch returns, and processing runs in the background task, so it
 * overlaps the next batch's fetch.
 */
export class LogsIngestionFrameworkConsumer {
    protected name = 'LogsIngestionConsumer'
    // Billing identity for quota enforcement and usage metering; overridden by subclasses (e.g. traces).
    protected quotaResource: QuotaResource = 'logs_mb_ingested'
    protected appSource: 'logs' | 'traces' = 'logs'
    // Record source this consumer tallies metric rules for. `appSource` is the billing/telemetry
    // identity ('logs' | 'traces'); metric rules use the record source ('logs' | 'spans').
    protected metricRuleSource: MetricRuleSource = 'logs'
    // Record source this consumer evaluates retention rules for, in the record vocabulary.
    protected retentionRuleSource: RetentionRuleSource = 'logs'
    protected kafkaConsumer: KafkaConsumerInterface
    private readonly appMetricsAggregator: AppMetricsAggregator
    private readonly redis: RedisV2
    private readonly rateLimiter: LogsRateLimiterService
    private readonly internalLogsVerifier: InternalLogsVerifier
    private readonly samplingService: LogsSamplingService
    private readonly metricSeriesAdmission = new MetricSeriesAdmission()
    private readonly gates: LogsFeatureGates
    // Subclass field initializers run after this constructor, so the identity they override is read
    // when the first batch builds the context, not here.
    private pipelineContext?: LogsPipelineContext

    protected groupId: string
    protected topic: string

    constructor(
        config: LogsIngestionConsumerConfig,
        private deps: LogsIngestionConsumerDeps,
        overrides: Partial<LogsIngestionConsumerConfig> = {},
        // Redis key namespace for the token-bucket rate limiter. Subclasses (e.g. traces) pass
        // their own so their per-team buckets don't share state with logs. Defaults to logs.
        rateLimiterName: string = 'logs-rate-limiter'
    ) {
        // Merge overrides once so every downstream consumer reads the same effective config.
        const mergedConfig = { ...config, ...overrides }

        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = mergedConfig.LOGS_INGESTION_CONSUMER_GROUP_ID
        this.topic = mergedConfig.LOGS_INGESTION_CONSUMER_CONSUME_TOPIC

        this.appMetricsAggregator = new AppMetricsAggregator(deps.outputs)

        this.kafkaConsumer = createKafkaConsumer({ groupId: this.groupId, topic: this.topic })
        // Logs ingestion uses its own Redis instance with TLS support
        this.redis = createRedisV2PoolFromConfig({
            connection: mergedConfig.LOGS_REDIS_HOST
                ? {
                      url: mergedConfig.LOGS_REDIS_HOST,
                      options: {
                          port: mergedConfig.LOGS_REDIS_PORT,
                          tls: mergedConfig.LOGS_REDIS_TLS ? {} : undefined,
                      },
                      name: 'logs-redis',
                  }
                : { url: mergedConfig.REDIS_URL, name: 'logs-redis-fallback' },
            poolMinSize: mergedConfig.REDIS_POOL_MIN_SIZE,
            poolMaxSize: mergedConfig.REDIS_POOL_MAX_SIZE,
        })
        this.rateLimiter = new LogsRateLimiterService(mergedConfig, this.redis, rateLimiterName)
        this.internalLogsVerifier = new InternalLogsVerifier(
            mergedConfig.LOGS_INTERNAL_INGESTION_SIGNING_KEYS,
            mergedConfig.LOGS_INTERNAL_INGESTION_ENABLED_TEAMS,
            deps.internalSourcePolicies
        )
        this.samplingService = new LogsSamplingService(this.redis, mergedConfig.LOGS_LIMITER_TTL_SECONDS)
        this.gates = {
            backfillEnabledTeams: mergedConfig.LOGS_BACKFILL_ENABLED_TEAMS,
            samplingEnabledTeams: mergedConfig.LOGS_SAMPLING_ENABLED_TEAMS,
            samplingKillswitch: mergedConfig.LOGS_SAMPLING_KILLSWITCH,
            billingProrateEnabled: mergedConfig.LOGS_BILLING_PRORATE_ENABLED,
            metricRulesEnabledTeams: mergedConfig.LOGS_METRICS_RULES_ENABLED_TEAMS,
            metricRulesKillswitch: mergedConfig.LOGS_METRICS_RULES_KILLSWITCH,
            defaultMetricRulesEnabledTeams: mergedConfig.LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS,
            transformationsEnabledTeams: mergedConfig.LOGS_TRANSFORMATIONS_ENABLED_TEAMS,
            transformationsKillswitch: mergedConfig.LOGS_TRANSFORMATIONS_KILLSWITCH,
            retentionEnabledTeams: mergedConfig.LOGS_RETENTION_ENABLED_TEAMS,
            retentionKillswitch: mergedConfig.LOGS_RETENTION_KILLSWITCH,
            patternMaskingEnabledTeams: mergedConfig.LOGS_PATTERN_MASKING_ENABLED_TEAMS,
            jsonAttributeParsingEnabledTeams: mergedConfig.LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS,
            jsonAttributeExtractionEnabledTeams: mergedConfig.LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS,
        }
    }

    /**
     * The team's default retention period, applied to records no rule matches and sent as the
     * batch `retention-days` Kafka header. Traces override this to read their own setting.
     */
    protected defaultRetentionDays(_teamId: number, logsSettings: LogsSettings): Promise<number> {
        return Promise.resolve(logsSettings.retention_days ?? DEFAULT_LOGS_RETENTION_DAYS)
    }

    /**
     * Long-lived state the steps share. The pipelines themselves are built per batch: they are cheap,
     * and a chunk pipeline instance shared by overlapping calls would mix their messages.
     */
    private getPipelineContext(): LogsPipelineContext {
        if (!this.pipelineContext) {
            const identity: LogsConsumerIdentity = {
                name: this.name,
                appSource: this.appSource,
                quotaResource: this.quotaResource,
                metricRuleSource: this.metricRuleSource,
                retentionRuleSource: this.retentionRuleSource,
            }
            this.pipelineContext = {
                identity,
                gates: this.gates,
                deps: this.deps,
                usageMetrics: new LogsUsageMetricsQueue(this.appMetricsAggregator, identity.appSource),
                rateLimiter: this.rateLimiter,
                samplingService: this.samplingService,
                internalLogsVerifier: this.internalLogsVerifier,
                metricSeriesAdmission: this.metricSeriesAdmission,
                defaultRetentionDays: (teamId, logsSettings) => this.defaultRetentionDays(teamId, logsSettings),
            }
        }
        return this.pipelineContext
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    @instrumented('logsIngestionConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<LogsIngestionMessage[]> {
        return await runChunkPipeline(
            createLogsParsePipeline(this.getPipelineContext()),
            messages.map((message) => ({ message }))
        )
    }

    /**
     * Runs the gates over parsed messages. Returns the messages to process (billed first, then
     * unbilled internal) and a background task that processes them, emits the batch's metric
     * tallies and usage, and rejects if the batch must be replayed.
     */
    public async processBatch(
        messages: LogsIngestionMessage[]
    ): Promise<{ backgroundTask?: Promise<any>; messages: LogsIngestionMessage[] }> {
        if (!messages.length) {
            return { messages: [] }
        }
        const context = this.getPipelineContext()

        const usage = new LogsBatchUsage()
        const admitted = await runChunkPipeline<LogsAdmissionInput, LogsAdmissionInput, Record<string, never>>(
            createLogsAdmissionPipeline(context),
            messages.map((message) => ({ ...message, usage }))
        )
        reportDroppedUsage(usage)

        const billed: LogsIngestionMessage[] = []
        const internal: LogsIngestionMessage[] = []
        for (const { usage: _usage, ...message } of admitted) {
            ;(isUnbilledInternal(message) ? internal : billed).push(message)
        }

        // One transformation time budget shared by all messages of this batch.
        const transformationBudget = this.deps.logsTransformer?.startBatch()

        return {
            backgroundTask: this.processAdmitted(context, billed, internal, usage.byTeam, transformationBudget),
            messages: [...billed, ...internal],
        }
    }

    private async processAdmitted(
        context: LogsPipelineContext,
        billed: LogsIngestionMessage[],
        internal: LogsIngestionMessage[],
        usageStats: UsageStatsByTeam,
        transformationBudget?: TransformationBatchBudget
    ): Promise<void> {
        // Produce first, so PII replacement counts are in the usage rows before they are emitted.
        const billedPass: LogsProcessingPass = { usage: usageStats, metricTallies: new Map(), transformationBudget }
        await this.runProcessingPass(context, billed, billedPass)
        // Rows that are never emitted keep internal stats off the team's billed usage. Internal
        // messages run after the billed ones, so the per-batch concurrency limit still holds.
        await this.runProcessingPass(context, internal, {
            usage: new Map(),
            metricTallies: new Map() as MetricTalliesByTeam,
            transformationBudget,
        })
        // Metric rules and internal usage emit deltas, so they wait until no pass can fail the
        // batch into a replay.
        queueInternalLogsUsage(context, internal)
        await emitMetricRuleTallies(context, billedPass.metricTallies)
        await this.deps.teamManager.setTeamsIngestedData(billed.map((message) => message.teamId))
        await emitUsageMetrics(context, usageStats)
        // Best-effort flush of transformation app metrics + function logs; never block the data path.
        if (this.deps.logsTransformer) {
            await this.deps.logsTransformer.flush().catch((error) => {
                logger.error('Failed to flush logs transformer monitoring', { error: String(error) })
            })
        }
    }

    private async runProcessingPass(
        context: LogsPipelineContext,
        messages: LogsIngestionMessage[],
        pass: LogsProcessingPass
    ): Promise<void> {
        await runChunkPipeline(
            createLogsProcessingPipeline(context),
            messages.map((message) => ({ ...message, pass }))
        )
    }

    public async processKafkaBatch(
        messages: Message[]
    ): Promise<{ backgroundTask?: Promise<any>; messages: LogsIngestionMessage[] }> {
        try {
            const events = await this._parseKafkaBatch(messages)
            return await this.processBatch(events)
        } catch (error) {
            // Rethrow: the consumer deliberately lets a batch failure crash the process, which is
            // what preserves at-least-once. We do not DLQ here — everything on this path (quota
            // lookups, the rate limiter) is infrastructure-scoped, and quarantining a whole batch
            // over a Redis blip would drop good data. Name the records first so the restart loop
            // that follows points somewhere.
            logger.error('🔴', `${this.name} - batch failed`, {
                error: String(error),
                stack: error instanceof Error ? error.stack : undefined,
                size: messages.length,
                offsets: describeBatchPosition(messages),
            })
            throw error
        }
    }

    public async start(): Promise<void> {
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
                offsets: describeBatchPosition(messages),
            })

            return await instrumentFn('logsIngestionConsumer.handleEachBatch', async () => {
                return await this.processKafkaBatch(messages)
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
