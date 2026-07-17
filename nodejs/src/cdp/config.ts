import {
    KAFKA_APP_METRICS_2,
    KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
    KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
    KAFKA_EVENTS_JSON,
    KAFKA_HOG_INVOCATION_RESULTS,
    KAFKA_LOG_ENTRIES,
    KAFKA_MESSAGE_ASSETS,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS,
} from '~/common/config/kafka-topics'
import { isDevEnv, isProdEnv, isTestEnv } from '~/common/utils/env-utils'

import { ClickhouseConfig, getDefaultClickhouseConfig } from '../common/clickhouse-config'
import {
    CdpProducerName,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CALCULATED_EVENTS_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from './outputs/producers'
import { CyclotronJobQueueKind, CyclotronJobQueueSource } from './types'

// CdpConfig intersects ClickhouseConfig so any consumer reading
// `this.config.CLICKHOUSE_HOST` etc. gets typed, defaulted values — fixes the
// case where `CdpRerunWorkerConsumer` silently fell back to `default` DB.
export type CdpConfig = ClickhouseConfig & {
    CDP_WATCHER_COST_ERROR: number
    CDP_WATCHER_HOG_COST_TIMING: number
    CDP_WATCHER_HOG_COST_TIMING_LOWER_MS: number
    CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: number
    CDP_WATCHER_ASYNC_COST_TIMING: number
    CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS: number
    CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS: number
    CDP_WATCHER_THRESHOLD_DEGRADED: number
    CDP_WATCHER_BUCKET_SIZE: number
    CDP_WATCHER_TTL: number
    CDP_WATCHER_STATE_LOCK_TTL: number
    CDP_WATCHER_REFILL_RATE: number
    CDP_WATCHER_DISABLED_TEMPORARY_TTL: number
    CDP_WATCHER_DISABLED_TEMPORARY_MAX_COUNT: number
    CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS: boolean
    CDP_WATCHER_SEND_EVENTS: boolean
    CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS: number
    CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS: number
    CDP_RATE_LIMITER_BUCKET_SIZE: number
    CDP_RATE_LIMITER_REFILL_RATE: number
    CDP_RATE_LIMITER_TTL: number
    CDP_HOG_FILTERS_TELEMETRY_TEAMS: string
    DISABLE_OPENTELEMETRY_TRACING: boolean
    CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_KIND: CyclotronJobQueueKind
    CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: CyclotronJobQueueSource
    CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: string

    CDP_LEGACY_EVENT_CONSUMER_GROUP_ID: string
    CDP_LEGACY_EVENT_CONSUMER_TOPIC: string
    CDP_LEGACY_EVENT_CONSUMER_INCLUDE_WEBHOOKS: boolean

    CDP_CYCLOTRON_BATCH_DELAY_MS: number
    CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS: number
    CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: number
    CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: boolean
    CDP_CYCLOTRON_COMPRESS_VM_STATE: boolean
    CDP_CYCLOTRON_USE_BULK_COPY_JOB: boolean
    CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: boolean
    CDP_REDIS_HOST: string
    CDP_REDIS_PORT: number
    CDP_REDIS_PASSWORD: string
    // Reuses CDP_REDIS_PASSWORD; falls back to the writer when host is unset.
    CDP_REDIS_READER_HOST: string
    CDP_REDIS_READER_PORT: number

    // Shadow Valkey pool for dual-write/read load testing. When CDP_VALKEY_DUAL_ENABLED
    // is true and CDP_VALKEY_HOST is set, every Redis call also runs against this pool;
    // shadow results are discarded, errors/timeouts logged + counted but never affect
    // the primary code path.
    CDP_VALKEY_HOST: string
    CDP_VALKEY_PORT: number
    CDP_VALKEY_PASSWORD: string
    CDP_VALKEY_READER_HOST: string
    CDP_VALKEY_READER_PORT: number
    CDP_VALKEY_DUAL_ENABLED: boolean
    // AWS ElastiCache Valkey Serverless requires TLS; toggle off only for local non-TLS test setups.
    CDP_VALKEY_TLS: boolean

    SES_RATE_LIMITER_VALKEY_HOST: string
    SES_RATE_LIMITER_VALKEY_PORT: number
    SES_RATE_LIMITER_VALKEY_PASSWORD: string
    SES_RATE_LIMITER_VALKEY_TLS: boolean

    CDP_SES_RATE_LIMIT_REFILL_PER_SECOND: number
    CDP_SES_RATE_LIMIT_CAPACITY: number
    CDP_SES_RATE_LIMIT_THROTTLED_POLL_DELAY_MS: number

    CDP_EVENT_PROCESSOR_EXECUTE_FIRST_STEP: boolean
    CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN: string
    CDP_FETCH_RETRIES: number
    CDP_FETCH_BACKOFF_BASE_MS: number
    CDP_FETCH_BACKOFF_MAX_MS: number
    CDP_OVERFLOW_QUEUE_ENABLED: boolean
    HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC: string
    HOG_FUNCTION_MONITORING_APP_METRICS_PRODUCER: CdpProducerName
    HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC: string
    HOG_FUNCTION_MONITORING_LOG_ENTRIES_PRODUCER: CdpProducerName
    HOG_INVOCATION_RESULTS_TOPIC: string
    HOG_INVOCATION_RESULTS_PRODUCER: CdpProducerName
    HOG_INVOCATION_RESULTS_ENABLED: boolean
    // Message assets: rendered emails snapshotted to object storage + a metadata
    // row in the message_assets ClickHouse table, surfaced in the workflow
    // "Assets" tab.
    MESSAGE_ASSETS_TOPIC: string
    MESSAGE_ASSETS_PRODUCER: CdpProducerName
    HOG_INVOCATION_RERUN_MAX_COUNT: number
    // How many rerun wrapper jobs the worker dequeues per cyclotron-v2 poll.
    // Kept small by default — each job runs a full ClickHouse query per page.
    CDP_RERUN_WORKER_BATCH_SIZE: number
    CDP_PREFILTERED_EVENTS_TOPIC: string
    CDP_PREFILTERED_EVENTS_PRODUCER: CdpProducerName
    CDP_PRECALCULATED_PERSON_PROPERTIES_TOPIC: string
    CDP_PRECALCULATED_PERSON_PROPERTIES_PRODUCER: CdpProducerName
    CDP_WAREHOUSE_SOURCE_WEBHOOKS_TOPIC: string
    CDP_WAREHOUSE_SOURCE_WEBHOOKS_PRODUCER: CdpProducerName

    CDP_EMAIL_TRACKING_URL: string

    // Cyclotron (CDP job queue)
    CYCLOTRON_DATABASE_URL: string
    CYCLOTRON_SHARD_DEPTH_LIMIT: number
    CYCLOTRON_NODE_DATABASE_URL?: string
    // SES (Workflows email sending)
    SES_ENDPOINT: string
    SES_ACCESS_KEY_ID: string
    SES_SECRET_ACCESS_KEY: string
    SES_REGION: string

    // Destination migration diffing
    DESTINATION_MIGRATION_DIFFING_ENABLED: boolean

    CDP_BATCH_WORKFLOW_MAX_AUDIENCE_SIZE: number

    // Cyclotron Node (node postgres job queue)
    CYCLOTRON_NODE_MAX_CONNECTIONS: number
    CYCLOTRON_NODE_IDLE_TIMEOUT_MS: number
    CYCLOTRON_NODE_JANITOR_CLEANUP_BATCH_SIZE: number
    CYCLOTRON_NODE_JANITOR_CLEANUP_INTERVAL_MS: number
    CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: number
    CYCLOTRON_NODE_JANITOR_MAX_TOUCH_COUNT: number
    CYCLOTRON_NODE_JANITOR_CLEANUP_GRACE_MS: number
    // Kill-switch for poison-pill recovery. When false the janitor reverts to
    // master's pre-recovery behavior — mark poison pills failed with no replay
    // record (a give-up is lost, exactly as before this change). Flip to false to
    // roll back the recovery machinery instantly without a redeploy. Default true.
    CYCLOTRON_NODE_POISON_PILL_RECOVERY_ENABLED: boolean
    // Backoff on a stalled job's next scheduled time per janitor reset, keyed on
    // janitor_touch_count. The first stall retries within seconds (so a transient
    // stall / worker restart recovers fast); repeat stalls back off exponentially —
    // at the defaults roughly ~30-60s, then ~1.5-3min, before give-up. Jittered
    // throughout to de-sync a fleet-wide herd. Base 0 disables it (immediate retry);
    // max caps the per-strike wait.
    CYCLOTRON_NODE_JANITOR_STALL_BACKOFF_BASE_MS: number
    CYCLOTRON_NODE_JANITOR_STALL_BACKOFF_MAX_MS: number
    // Timing-edit reschedule sweep (CyclotronV2Manager.rescheduleParkedJobs)
    // Scoped JWT keys authenticating Django's calls to the reschedule_parked route — comma-separated,
    // newest first (first signs, all verify). Deliberately NOT the fleet-wide INTERNAL_API_SECRET
    // (see .agents/security.md): empty in prod means the route fails closed until provisioned.
    WORKFLOWS_RESCHEDULE_JWT_SECRET: string
    CYCLOTRON_NODE_RESCHEDULE_FLOOR_SECONDS: number
    CYCLOTRON_NODE_RESCHEDULE_WAKE_RATE_PER_SECOND: number
    CYCLOTRON_NODE_RESCHEDULE_MIN_WINDOW_SECONDS: number
    CYCLOTRON_NODE_RESCHEDULE_MAX_WINDOW_SECONDS: number
    CYCLOTRON_NODE_RESCHEDULE_CHUNK_SIZE: number
    CYCLOTRON_NODE_RESCHEDULE_MAX_CHUNKS_PER_CALL: number
    CYCLOTRON_NODE_RESCHEDULE_CHUNK_SLEEP_MS: number
}

export function getDefaultCdpConfig(): CdpConfig {
    return {
        ...getDefaultClickhouseConfig(),
        CDP_WATCHER_COST_ERROR: 100,
        CDP_WATCHER_HOG_COST_TIMING: 100,
        CDP_WATCHER_HOG_COST_TIMING_LOWER_MS: 50,
        CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: 550,
        CDP_WATCHER_ASYNC_COST_TIMING: 20,
        CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS: 100,
        CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS: 5000,
        CDP_WATCHER_THRESHOLD_DEGRADED: 0.8,
        CDP_WATCHER_BUCKET_SIZE: 10000,
        CDP_WATCHER_TTL: 60 * 60 * 24,
        CDP_WATCHER_STATE_LOCK_TTL: 60,
        CDP_WATCHER_REFILL_RATE: 10,
        CDP_WATCHER_DISABLED_TEMPORARY_TTL: 60 * 10,
        CDP_WATCHER_DISABLED_TEMPORARY_MAX_COUNT: 3,
        CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS: isProdEnv() ? false : true,
        CDP_WATCHER_SEND_EVENTS: isProdEnv() ? false : true,
        CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS: 500,
        CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS: 500,
        CDP_RATE_LIMITER_BUCKET_SIZE: 10_000,
        CDP_RATE_LIMITER_REFILL_RATE: 100,
        CDP_RATE_LIMITER_TTL: 60 * 60 * 24,
        CDP_HOG_FILTERS_TELEMETRY_TEAMS: '',
        DISABLE_OPENTELEMETRY_TRACING: false,
        CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_KIND: 'hog',
        CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'kafka',
        CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',

        CDP_LEGACY_EVENT_CONSUMER_GROUP_ID: 'clickhouse-plugin-server-async-onevent',
        CDP_LEGACY_EVENT_CONSUMER_TOPIC: KAFKA_EVENTS_JSON,
        CDP_LEGACY_EVENT_CONSUMER_INCLUDE_WEBHOOKS: false,

        CDP_CYCLOTRON_BATCH_DELAY_MS: 50,
        CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS: 10000,
        CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 100,
        CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: true,
        CDP_CYCLOTRON_COMPRESS_VM_STATE: isProdEnv() ? false : true,
        CDP_CYCLOTRON_USE_BULK_COPY_JOB: isProdEnv() ? false : true,
        CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: true,
        CDP_REDIS_HOST: '127.0.0.1',
        CDP_REDIS_PORT: 6379,
        CDP_REDIS_PASSWORD: '',
        CDP_REDIS_READER_HOST: '',
        CDP_REDIS_READER_PORT: 6379,

        CDP_VALKEY_HOST: '',
        CDP_VALKEY_PORT: 6379,
        CDP_VALKEY_PASSWORD: '',
        CDP_VALKEY_READER_HOST: '',
        CDP_VALKEY_READER_PORT: 6379,
        CDP_VALKEY_DUAL_ENABLED: false,
        CDP_VALKEY_TLS: false,

        SES_RATE_LIMITER_VALKEY_HOST: '',
        SES_RATE_LIMITER_VALKEY_PORT: 6379,
        SES_RATE_LIMITER_VALKEY_PASSWORD: '',
        SES_RATE_LIMITER_VALKEY_TLS: false,

        CDP_SES_RATE_LIMIT_REFILL_PER_SECOND: 100,
        CDP_SES_RATE_LIMIT_CAPACITY: 50,
        CDP_SES_RATE_LIMIT_THROTTLED_POLL_DELAY_MS: 250,

        CDP_EVENT_PROCESSOR_EXECUTE_FIRST_STEP: true,
        CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN: '',
        CDP_FETCH_RETRIES: 3,
        CDP_FETCH_BACKOFF_BASE_MS: 1000,
        CDP_FETCH_BACKOFF_MAX_MS: 30000,
        CDP_OVERFLOW_QUEUE_ENABLED: false,
        HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC: KAFKA_APP_METRICS_2,
        HOG_FUNCTION_MONITORING_APP_METRICS_PRODUCER: WARPSTREAM_INGESTION_PRODUCER,
        HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC: KAFKA_LOG_ENTRIES,
        HOG_FUNCTION_MONITORING_LOG_ENTRIES_PRODUCER: WARPSTREAM_INGESTION_PRODUCER,
        HOG_INVOCATION_RESULTS_TOPIC: KAFKA_HOG_INVOCATION_RESULTS,
        // Cyclotron Warpstream cluster — ClickHouse consumes hog_invocation_results
        // from the warpstream_cyclotron named collection, so the producer must
        // target the same cluster.
        HOG_INVOCATION_RESULTS_PRODUCER: WARPSTREAM_CYCLOTRON_PRODUCER,
        // Off by default — flip to true once the table is migrated and we want to start writing.
        // Per-team rollout still happens at the call site.
        HOG_INVOCATION_RESULTS_ENABLED: isDevEnv() ? true : false,
        MESSAGE_ASSETS_TOPIC: KAFKA_MESSAGE_ASSETS,
        // Same cyclotron Warpstream cluster as hog_invocation_results — ClickHouse
        // consumes message_assets from the warpstream_cyclotron named collection.
        MESSAGE_ASSETS_PRODUCER: WARPSTREAM_CYCLOTRON_PRODUCER,
        // Hard cap on rows a single rerun wrapper job will drain. Mirrors the
        // Django serializer's HOG_INVOCATION_RERUN_MAX_COUNT (same env var).
        HOG_INVOCATION_RERUN_MAX_COUNT: 10000,
        // Small by default — rerun jobs are heavy (a full ClickHouse query per
        // page), so a replica drains one wrapper job at a time unless tuned up.
        CDP_RERUN_WORKER_BATCH_SIZE: 1,
        CDP_PREFILTERED_EVENTS_TOPIC: KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
        CDP_PREFILTERED_EVENTS_PRODUCER: WARPSTREAM_CALCULATED_EVENTS_PRODUCER,
        CDP_PRECALCULATED_PERSON_PROPERTIES_TOPIC: KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
        CDP_PRECALCULATED_PERSON_PROPERTIES_PRODUCER: WARPSTREAM_CALCULATED_EVENTS_PRODUCER,
        CDP_WAREHOUSE_SOURCE_WEBHOOKS_TOPIC: KAFKA_WAREHOUSE_SOURCE_WEBHOOKS,
        CDP_WAREHOUSE_SOURCE_WEBHOOKS_PRODUCER: WAREHOUSE_PRODUCER,

        CDP_EMAIL_TRACKING_URL: 'http://localhost:8010',

        // Cyclotron
        CYCLOTRON_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_cyclotron'
            : 'postgres://posthog:posthog@localhost:5432/cyclotron',
        CYCLOTRON_SHARD_DEPTH_LIMIT: 1000000,
        CYCLOTRON_NODE_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/cyclotron_node'
              : undefined,

        // SES
        SES_ENDPOINT: isTestEnv() || isDevEnv() ? 'http://localhost:4566' : '',
        SES_ACCESS_KEY_ID: isTestEnv() || isDevEnv() ? 'test' : '',
        SES_SECRET_ACCESS_KEY: isTestEnv() || isDevEnv() ? 'test' : '',
        SES_REGION: isTestEnv() || isDevEnv() ? 'us-east-1' : '',

        // Destination migration diffing
        DESTINATION_MIGRATION_DIFFING_ENABLED: false,

        // Fallback cap used only when a batch-resolve API caller does not pass max_audience_size.
        // Django's batch-job model always passes get_hogflow_batch_trigger_limit(team_id), so
        // production batches use the per-team value from settings; this is only a safety net for
        // direct callers (tests, admin tools). Match the fleet-wide default in settings.web.py.
        CDP_BATCH_WORKFLOW_MAX_AUDIENCE_SIZE: 50000,

        // Cyclotron Node
        CYCLOTRON_NODE_MAX_CONNECTIONS: 10,
        CYCLOTRON_NODE_IDLE_TIMEOUT_MS: 30000,
        CYCLOTRON_NODE_JANITOR_CLEANUP_BATCH_SIZE: 10000,
        CYCLOTRON_NODE_JANITOR_CLEANUP_INTERVAL_MS: 10000,
        CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: 30000,
        CYCLOTRON_NODE_JANITOR_MAX_TOUCH_COUNT: 3,
        CYCLOTRON_NODE_JANITOR_CLEANUP_GRACE_MS: 10000,
        CYCLOTRON_NODE_POISON_PILL_RECOVERY_ENABLED: true,
        CYCLOTRON_NODE_JANITOR_STALL_BACKOFF_BASE_MS: 60000,
        CYCLOTRON_NODE_JANITOR_STALL_BACKOFF_MAX_MS: 600000,
        // Floor > the hog flow cache's worst-case staleness (~6 min), so swept jobs
        // always wake against post-edit config. Rate sized well under hogflow worker
        // steady-state throughput: the past incident class here is an instantaneous
        // mass wake, so wakes are trickled (500k parked @ 200/s ≈ 42 min spread).
        // Dev/test default must match Django's (posthog/settings/data_stores.py).
        WORKFLOWS_RESCHEDULE_JWT_SECRET: isTestEnv() || isDevEnv() ? 'local-dev-workflows-reschedule-jwt' : '',
        CYCLOTRON_NODE_RESCHEDULE_FLOOR_SECONDS: 600,
        CYCLOTRON_NODE_RESCHEDULE_WAKE_RATE_PER_SECOND: 200,
        CYCLOTRON_NODE_RESCHEDULE_MIN_WINDOW_SECONDS: 300,
        CYCLOTRON_NODE_RESCHEDULE_MAX_WINDOW_SECONDS: 14400,
        CYCLOTRON_NODE_RESCHEDULE_CHUNK_SIZE: 5000,
        CYCLOTRON_NODE_RESCHEDULE_MAX_CHUNKS_PER_CALL: 20,
        CYCLOTRON_NODE_RESCHEDULE_CHUNK_SLEEP_MS: 100,
    }
}
