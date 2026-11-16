import type { LogsSettings } from '~/types'

import { LogsIngestionConsumerConfig, TracesIngestionConsumerConfig } from '../config'
import type { MetricRuleSource } from '../metrics-rules/compile-metric-rules'
import type { RetentionRuleSource } from '../retention/compile-retention-rules'
import { DEFAULT_TRACES_RETENTION_DAYS, TracingConfigCache } from '../retention/tracing-config-cache'
import type { TracesIngestionConsumerDeps } from '../traces-ingestion-consumer'
import { LogsIngestionFrameworkConsumer } from './logs-ingestion-framework-consumer'

/** Keep the config overrides in step with `TracesIngestionConsumer`. */
export class TracesIngestionFrameworkConsumer extends LogsIngestionFrameworkConsumer {
    protected override name = 'TracesIngestionConsumer'
    // Traces bill against the shared logs bucket, so the inherited quota resource stays.
    protected override appSource: 'logs' | 'traces' = 'traces'
    protected override metricRuleSource: MetricRuleSource = 'spans'
    protected override retentionRuleSource: RetentionRuleSource = 'spans'
    private tracingConfigCache?: TracingConfigCache

    constructor(
        config: LogsIngestionConsumerConfig & TracesIngestionConsumerConfig,
        deps: TracesIngestionConsumerDeps
    ) {
        super(
            config,
            deps,
            {
                LOGS_INGESTION_CONSUMER_GROUP_ID: config.TRACES_INGESTION_CONSUMER_GROUP_ID,
                LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: config.TRACES_INGESTION_CONSUMER_CONSUME_TOPIC,
                LOGS_REDIS_HOST: config.TRACES_REDIS_HOST,
                LOGS_REDIS_PORT: config.TRACES_REDIS_PORT,
                LOGS_REDIS_PASSWORD: config.TRACES_REDIS_PASSWORD,
                LOGS_REDIS_TLS: config.TRACES_REDIS_TLS,
                LOGS_LIMITER_ENABLED_TEAMS: config.TRACES_LIMITER_ENABLED_TEAMS,
                LOGS_LIMITER_DISABLED_FOR_TEAMS: config.TRACES_LIMITER_DISABLED_FOR_TEAMS,
                LOGS_LIMITER_BUCKET_SIZE_KB: config.TRACES_LIMITER_BUCKET_SIZE_KB,
                LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: config.TRACES_LIMITER_REFILL_RATE_KB_PER_SECOND,
                LOGS_LIMITER_TTL_SECONDS: config.TRACES_LIMITER_TTL_SECONDS,
                LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: config.TRACES_LIMITER_TEAM_BUCKET_SIZE_KB,
                LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: config.TRACES_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND,
                LOGS_METRICS_RULES_ENABLED_TEAMS: config.TRACES_METRICS_RULES_ENABLED_TEAMS,
                LOGS_METRICS_RULES_KILLSWITCH: config.TRACES_METRICS_RULES_KILLSWITCH,
                LOGS_METRICS_RULES_EXPORT_URL: config.TRACES_METRICS_RULES_EXPORT_URL,
                LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS: config.TRACES_DEFAULT_METRIC_RULES_ENABLED_TEAMS,
                LOGS_RETENTION_ENABLED_TEAMS: config.TRACES_RETENTION_ENABLED_TEAMS,
                LOGS_RETENTION_KILLSWITCH: config.TRACES_RETENTION_KILLSWITCH,
                // Internal batches are logs only, so a signed traces batch is still billed.
                LOGS_INTERNAL_INGESTION_SIGNING_KEYS: '',
                LOGS_INTERNAL_INGESTION_ENABLED_TEAMS: '',
            },
            'traces-rate-limiter'
        )
        this.tracingConfigCache = deps.tracingConfigCache
    }

    protected override async defaultRetentionDays(teamId: number, _logsSettings: LogsSettings): Promise<number> {
        if (!this.tracingConfigCache) {
            return DEFAULT_TRACES_RETENTION_DAYS
        }
        return await this.tracingConfigCache.getRetentionDays(teamId)
    }
}
