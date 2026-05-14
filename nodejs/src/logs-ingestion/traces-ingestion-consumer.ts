import { LogsIngestionConsumerConfig, TracesIngestionConsumerConfig } from './config'
import { LogsIngestionConsumer, LogsIngestionConsumerDeps } from './logs-ingestion-consumer'

export class TracesIngestionConsumer extends LogsIngestionConsumer {
    protected override name = 'TracesIngestionConsumer'

    constructor(config: LogsIngestionConsumerConfig & TracesIngestionConsumerConfig, deps: LogsIngestionConsumerDeps) {
        // Topics are wired into `deps.outputs` by the server, so the only consumer-level
        // overrides left are the consume topic / group / Redis / rate-limiter settings.
        super(config, deps, {
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
        })
    }
}
