# IngestionGeneralServerConfig — flat key list

All config keys required by `IngestionGeneralServerConfig`, resolved from its constituent types.

## BaseServerConfig (9 keys)

| Key                                    | Type      |
| -------------------------------------- | --------- |
| `INTERNAL_API_SECRET`                  | `string`  |
| `INSTRUMENT_THREAD_PERFORMANCE`        | `boolean` |
| `HTTP_SERVER_PORT`                     | `number`  |
| `POD_TERMINATION_ENABLED`              | `boolean` |
| `POD_TERMINATION_BASE_TIMEOUT_MINUTES` | `number`  |
| `POD_TERMINATION_JITTER_MINUTES`       | `number`  |
| `CONTINUOUS_PROFILING_ENABLED`         | `boolean` |
| `PYROSCOPE_SERVER_ADDRESS`             | `string`  |
| `PYROSCOPE_APPLICATION_NAME`           | `string`  |

## KafkaBrokerConfig (9 keys)

| Key                         | Type                                 |
| --------------------------- | ------------------------------------ |
| `KAFKA_HOSTS`               | `string`                             |
| `KAFKA_SECURITY_PROTOCOL`   | `KafkaSecurityProtocol \| undefined` |
| `KAFKA_CLIENT_RACK`         | `string \| undefined`                |
| `KAFKA_CLIENT_CERT_B64`     | `string \| undefined`                |
| `KAFKA_CLIENT_CERT_KEY_B64` | `string \| undefined`                |
| `KAFKA_TRUSTED_CERT_B64`    | `string \| undefined`                |
| `KAFKA_SASL_MECHANISM`      | `KafkaSaslMechanism \| undefined`    |
| `KAFKA_SASL_USER`           | `string \| undefined`                |
| `KAFKA_SASL_PASSWORD`       | `string \| undefined`                |

## DatabaseConnectionConfig (6 keys)

`Omit<PostgresRouterConfig, 'BEHAVIORAL_COHORTS_DATABASE_URL'>`

| Key                             | Type             | Required |
| ------------------------------- | ---------------- | -------- |
| `PLUGIN_SERVER_MODE`            | `string \| null` | yes      |
| `DATABASE_URL`                  | `string`         | yes      |
| `POSTGRES_CONNECTION_POOL_SIZE` | `number`         | yes      |
| `DATABASE_READONLY_URL`         | `string`         | optional |
| `PLUGIN_STORAGE_DATABASE_URL`   | `string`         | optional |
| `PERSONS_DATABASE_URL`          | `string`         | optional |
| `PERSONS_READONLY_DATABASE_URL` | `string`         | optional |

## RedisConnectionsConfig (8 keys)

| Key                      | Type     |
| ------------------------ | -------- |
| `REDIS_URL`              | `string` |
| `REDIS_POOL_MIN_SIZE`    | `number` |
| `REDIS_POOL_MAX_SIZE`    | `number` |
| `INGESTION_REDIS_HOST`   | `string` |
| `INGESTION_REDIS_PORT`   | `number` |
| `POSTHOG_REDIS_HOST`     | `string` |
| `POSTHOG_REDIS_PORT`     | `number` |
| `POSTHOG_REDIS_PASSWORD` | `string` |

## KafkaConsumerBaseConfig (8 keys)

| Key                                               | Type       |
| ------------------------------------------------- | ---------- |
| `CONSUMER_BATCH_SIZE`                             | `number`   |
| `CONSUMER_MAX_HEARTBEAT_INTERVAL_MS`              | `number`   |
| `CONSUMER_LOOP_STALL_THRESHOLD_MS`                | `number`   |
| `CONSUMER_LOG_STATS_LEVEL`                        | `LogLevel` |
| `CONSUMER_LOOP_BASED_HEALTH_CHECK`                | `boolean`  |
| `CONSUMER_MAX_BACKGROUND_TASKS`                   | `number`   |
| `CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE` | `boolean`  |
| `CONSUMER_AUTO_CREATE_TOPICS`                     | `boolean`  |

## HogTransformerServiceConfig (via CdpCoreServicesConfig + 1 key)

### From CommonConfig (6 keys)

| Key                           | Type     |
| ----------------------------- | -------- |
| `REDIS_URL`                   | `string` |
| `REDIS_POOL_MIN_SIZE`         | `number` |
| `REDIS_POOL_MAX_SIZE`         | `number` |
| `ENCRYPTION_SALT_KEYS`        | `string` |
| `SITE_URL`                    | `string` |
| `CDP_HOG_WATCHER_SAMPLE_RATE` | `number` |

### From CdpConfig (28 keys)

| Key                                              | Type      |
| ------------------------------------------------ | --------- |
| `CDP_REDIS_HOST`                                 | `string`  |
| `CDP_REDIS_PORT`                                 | `number`  |
| `CDP_REDIS_PASSWORD`                             | `string`  |
| `CDP_WATCHER_HOG_COST_TIMING`                    | `number`  |
| `CDP_WATCHER_HOG_COST_TIMING_LOWER_MS`           | `number`  |
| `CDP_WATCHER_HOG_COST_TIMING_UPPER_MS`           | `number`  |
| `CDP_WATCHER_ASYNC_COST_TIMING`                  | `number`  |
| `CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS`         | `number`  |
| `CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS`         | `number`  |
| `CDP_WATCHER_SEND_EVENTS`                        | `boolean` |
| `CDP_WATCHER_BUCKET_SIZE`                        | `number`  |
| `CDP_WATCHER_REFILL_RATE`                        | `number`  |
| `CDP_WATCHER_TTL`                                | `number`  |
| `CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS`    | `boolean` |
| `CDP_WATCHER_THRESHOLD_DEGRADED`                 | `number`  |
| `CDP_WATCHER_STATE_LOCK_TTL`                     | `number`  |
| `CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS`     | `number`  |
| `CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS` | `number`  |
| `SES_ACCESS_KEY_ID`                              | `string`  |
| `SES_SECRET_ACCESS_KEY`                          | `string`  |
| `SES_REGION`                                     | `string`  |
| `SES_ENDPOINT`                                   | `string`  |
| `CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN`             | `string`  |
| `CDP_FETCH_RETRIES`                              | `number`  |
| `CDP_FETCH_BACKOFF_BASE_MS`                      | `number`  |
| `CDP_FETCH_BACKOFF_MAX_MS`                       | `number`  |
| `HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC`      | `string`  |
| `HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC`      | `string`  |

## IngestionConsumerConfig (62 keys)

| Key                                                        | Type                            |
| ---------------------------------------------------------- | ------------------------------- |
| `INGESTION_LANE`                                           | `IngestionLane \| null`         |
| `INGESTION_CONSUMER_GROUP_ID`                              | `string`                        |
| `INGESTION_CONSUMER_CONSUME_TOPIC`                         | `string`                        |
| `INGESTION_CONSUMER_DLQ_TOPIC`                             | `string`                        |
| `INGESTION_CONSUMER_OVERFLOW_TOPIC`                        | `string`                        |
| `INGESTION_CONCURRENCY`                                    | `number`                        |
| `INGESTION_BATCH_SIZE`                                     | `number`                        |
| `INGESTION_OVERFLOW_ENABLED`                               | `boolean`                       |
| `INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID`            | `string`                        |
| `INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY`           | `boolean`                       |
| `PERSON_BATCH_WRITING_DB_WRITE_MODE`                       | `PersonBatchWritingDbWriteMode` |
| `PERSON_BATCH_WRITING_USE_BATCH_UPDATES`                   | `boolean`                       |
| `PERSON_BATCH_WRITING_OPTIMISTIC_UPDATES_ENABLED`          | `boolean`                       |
| `PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES`              | `number`                        |
| `PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES`       | `number`                        |
| `PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS` | `number`                        |
| `PERSONS_PREFETCH_ENABLED`                                 | `boolean`                       |
| `PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE`                  | `number`                        |
| `PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES`              | `number`                        |
| `PERSON_PROPERTIES_TRIM_TARGET_BYTES`                      | `number`                        |
| `PERSON_PROPERTIES_UPDATE_ALL`                             | `boolean`                       |
| `PERSON_JSONB_SIZE_ESTIMATE_ENABLE`                        | `number`                        |
| `PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT`                      | `number`                        |
| `PERSON_MERGE_ASYNC_TOPIC`                                 | `string`                        |
| `PERSON_MERGE_ASYNC_ENABLED`                               | `boolean`                       |
| `PERSON_MERGE_SYNC_BATCH_SIZE`                             | `number`                        |
| `GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES`               | `number`                        |
| `GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES`        | `number`                        |
| `GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS`  | `number`                        |
| `EVENT_OVERFLOW_BUCKET_CAPACITY`                           | `number`                        |
| `EVENT_OVERFLOW_BUCKET_REPLENISH_RATE`                     | `number`                        |
| `INGESTION_STATEFUL_OVERFLOW_ENABLED`                      | `boolean`                       |
| `INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS`            | `number`                        |
| `INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS`      | `number`                        |
| `DROP_EVENTS_BY_TOKEN_DISTINCT_ID`                         | `string`                        |
| `SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID`             | `string`                        |
| `MAX_TEAM_ID_TO_BUFFER_ANONYMOUS_EVENTS_FOR`               | `number`                        |
| `SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP`                    | `boolean`                       |
| `EVENT_SCHEMA_ENFORCEMENT_ENABLED`                         | `boolean`                       |
| `KAFKA_BATCH_START_LOGGING_ENABLED`                        | `boolean`                       |
| `INGESTION_AI_EVENT_SPLITTING_ENABLED`                     | `boolean`                       |
| `INGESTION_AI_EVENT_SPLITTING_TEAMS`                       | `string`                        |
| `CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC`                       | `string`                        |
| `CLICKHOUSE_AI_EVENTS_KAFKA_TOPIC`                         | `string`                        |
| `CLICKHOUSE_HEATMAPS_KAFKA_TOPIC`                          | `string`                        |
| `COOKIELESS_DISABLED`                                      | `boolean`                       |
| `COOKIELESS_FORCE_STATELESS_MODE`                          | `boolean`                       |
| `COOKIELESS_DELETE_EXPIRED_LOCAL_SALTS_INTERVAL_MS`        | `number`                        |
| `COOKIELESS_SESSION_TTL_SECONDS`                           | `number`                        |
| `COOKIELESS_SALT_TTL_SECONDS`                              | `number`                        |
| `COOKIELESS_SESSION_INACTIVITY_MS`                         | `number`                        |
| `COOKIELESS_IDENTIFIES_TTL_SECONDS`                        | `number`                        |
| `COOKIELESS_REDIS_HOST`                                    | `string`                        |
| `COOKIELESS_REDIS_PORT`                                    | `number`                        |
| `PROPERTY_DEFS_CONSUMER_GROUP_ID`                          | `string`                        |
| `PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC`                     | `string`                        |
| `PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS`                     | `string`                        |
| `PROPERTY_DEFS_WRITE_DISABLED`                             | `boolean`                       |
| `DISTINCT_ID_LRU_SIZE`                                     | `number`                        |
| `EVENT_PROPERTY_LRU_SIZE`                                  | `number`                        |
| `PERSON_INFO_CACHE_TTL`                                    | `number`                        |
| `INGESTION_PIPELINE`                                       | `string \| null`                |
| `PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE`                  | `string \| null`                |

## Direct Pick from CommonConfig (13 keys)

| Key                             | Type                       |
| ------------------------------- | -------------------------- |
| `LOG_LEVEL`                     | `LogLevel`                 |
| `PLUGIN_SERVER_MODE`            | `PluginServerMode \| null` |
| `CLOUD_DEPLOYMENT`              | `string \| null`           |
| `MMDB_FILE_LOCATION`            | `string`                   |
| `CAPTURE_INTERNAL_URL`          | `string`                   |
| `LAZY_LOADER_DEFAULT_BUFFER_MS` | `number`                   |
| `LAZY_LOADER_MAX_SIZE`          | `number`                   |
| `TASKS_PER_WORKER`              | `number`                   |
| `TASK_TIMEOUT`                  | `number`                   |
| `POSTHOG_API_KEY`               | `string`                   |
| `POSTHOG_HOST_URL`              | `string`                   |
| `HEALTHCHECK_MAX_STALE_SECONDS` | `number`                   |
| `KAFKA_HEALTHCHECK_SECONDS`     | `number`                   |

## Overlapping keys

Keys that appear in multiple constituent types (TypeScript merges them):

| Key                   | Appears in                                    |
| --------------------- | --------------------------------------------- |
| `PLUGIN_SERVER_MODE`  | DatabaseConnectionConfig, Direct Pick         |
| `REDIS_URL`           | RedisConnectionsConfig, CdpCoreServicesConfig |
| `REDIS_POOL_MIN_SIZE` | RedisConnectionsConfig, CdpCoreServicesConfig |
| `REDIS_POOL_MAX_SIZE` | RedisConnectionsConfig, CdpCoreServicesConfig |

## Summary

**Total unique keys: ~143**
