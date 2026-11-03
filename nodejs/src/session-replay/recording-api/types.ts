/**
 * Recording API Types
 *
 * Re-exports shared encryption types from session-replay/types.ts and adds
 * Recording API-specific types.
 */
import { CommonConfig } from '~/common/config'
import {
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
} from '~/common/config/kafka-topics'
import { isProdEnv } from '~/common/utils/env-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { SessionRecordingApiConfig, SessionRecordingConfig } from '~/ingestion/pipelines/sessionreplay/config'
import {
    INGESTION_SESSIONREPLAY_PRODUCER,
    type IngestionSessionreplayProducer,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

/**
 * Recording API's outputs are ClickHouse-bound deletion tombstones on the warpstream-replay
 * cluster, produced through the INGESTION_SESSIONREPLAY slot.
 */
export type RecordingApiProducerName = IngestionSessionreplayProducer

// Re-export all shared encryption types so existing recording-api imports still work
export {
    SessionKeyDeletedError,
    type DecryptResult,
    type DeleteKeyResult,
    type EncryptResult,
    type KeyStore,
    type RecordingDecryptor,
    type RecordingEncryptor,
    type SerializedSessionKey,
    type SessionKey,
    type SessionState,
} from '~/ingestion/pipelines/sessionreplay/shared/types'

/**
 * Recording-api authorization config.
 *
 * `RECORDING_API_JWT_SECRET` is a dedicated signing secret (comma-separated `new_key,old_key` for
 * rotation), kept off the fleet-wide `JWT_SIGNING_KEY` so only the designated minters can produce
 * valid tokens. `RECORDING_API_ALLOW_LEGACY_SECRET` keeps the old `X-Internal-Api-Secret` accepted
 * during migration; flip it off at cutover.
 */
export type RecordingApiAuthConfig = {
    RECORDING_API_JWT_SECRET: string
    RECORDING_API_ALLOW_LEGACY_SECRET: boolean
}

export function getDefaultRecordingApiAuthConfig(): RecordingApiAuthConfig {
    return {
        // Dev/test default matches the Django/Temporal minters so local end-to-end calls validate.
        RECORDING_API_JWT_SECRET: isProdEnv() ? '' : 'dev-recording-api-jwt-secret',
        RECORDING_API_ALLOW_LEGACY_SECRET: true,
    }
}

/**
 * Which routes a recording-api process serves. `internal` serves the service-to-service routes that
 * Django and Temporal call. `public` serves only the browser block route, so pods reachable from the
 * internet run none of the internal routes. `all` serves both, for local development.
 */
export type RecordingApiRole = 'internal' | 'public' | 'all'

/**
 * The browser block route's token buckets, sized in blocks since one request fetches one block. The token's `tier`
 * picks the bucket: `browser` for the player, and `free`/`paid`/`enterprise` for API callers, which mirror Django's
 * per-team snapshot API limits at 20 blocks per request. Enforced by default; false serves over-limit requests and
 * only counts them.
 */
export const REPLAY_BLOCK_TIERS = ['browser', 'free', 'paid', 'enterprise'] as const
export type ReplayBlockTier = (typeof REPLAY_BLOCK_TIERS)[number]
export type ReplayBlockBucket = { bucketSize: number; refillPerSecond: number }

export type RecordingApiBlocksConfig = {
    RECORDING_API_ROLE: string
    // Signs only browser block tokens. Kept apart from RECORDING_API_JWT_SECRET, so the internet-facing pods, which
    // hold only this one, cannot sign a service token for an internal route.
    RECORDING_API_BLOCKS_JWT_SECRET: string
    RECORDING_API_BLOCK_RATE_LIMIT_ENFORCED: boolean
    // JSON object of tier -> [bucket size, refill per second].
    RECORDING_API_BLOCK_RATE_LIMITS: string
    // Deadline for one KMS or DynamoDB attempt. The SDK makes two attempts.
    RECORDING_API_AWS_TIMEOUT_MS: number
    // Deadline for a Redis command and for checking a connection out of the pool.
    RECORDING_API_REDIS_TIMEOUT_MS: number
}

export function getDefaultRecordingApiBlocksConfig(): RecordingApiBlocksConfig {
    return {
        RECORDING_API_ROLE: 'internal',
        // Dev/test default matches the Django minter so local end-to-end calls validate.
        RECORDING_API_BLOCKS_JWT_SECRET: isProdEnv() ? '' : 'dev-recording-api-blocks-jwt-secret',
        RECORDING_API_BLOCK_RATE_LIMIT_ENFORCED: true,
        RECORDING_API_BLOCK_RATE_LIMITS: JSON.stringify({
            browser: [2000, 8],
            free: [240, 1200 / 3600],
            paid: [1200, 6000 / 3600],
            enterprise: [2000, 8000 / 3600],
        }),
        // Deletes, which are mostly KMS and DynamoDB calls, almost never take over 2.5s in total.
        RECORDING_API_AWS_TIMEOUT_MS: 5000,
        RECORDING_API_REDIS_TIMEOUT_MS: 2000,
    }
}

export function parseReplayBlockRateLimits(raw: string): Record<ReplayBlockTier, ReplayBlockBucket> {
    let parsed: Record<string, unknown>
    try {
        parsed = parseJSON(raw) as Record<string, unknown>
    } catch {
        throw new Error('Invalid RECORDING_API_BLOCK_RATE_LIMITS: not valid JSON')
    }
    const buckets = {} as Record<ReplayBlockTier, ReplayBlockBucket>
    for (const tier of REPLAY_BLOCK_TIERS) {
        const value = parsed?.[tier]
        if (
            !Array.isArray(value) ||
            value.length !== 2 ||
            !value.every((n) => typeof n === 'number' && Number.isFinite(n) && n > 0)
        ) {
            throw new Error(`Invalid RECORDING_API_BLOCK_RATE_LIMITS: '${tier}' needs [bucket size, refill per second]`)
        }
        buckets[tier] = { bucketSize: value[0], refillPerSecond: value[1] }
    }
    return buckets
}

export function parseRecordingApiRole(role: string): RecordingApiRole {
    if (role === 'internal' || role === 'public' || role === 'all') {
        return role
    }
    throw new Error(`Invalid RECORDING_API_ROLE '${role}': expected internal, public or all`)
}

/**
 * Configuration for the Recording API.
 * Postgres is passed as an explicit constructor param, not included here.
 */
export type RecordingApiConfig = Pick<
    CommonConfig,
    'KAFKA_CLIENT_RACK' | 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE' | 'INTERNAL_API_SECRET'
> &
    Pick<
        SessionRecordingApiConfig,
        | 'SESSION_RECORDING_API_REDIS_HOST'
        | 'SESSION_RECORDING_API_REDIS_PORT'
        | 'SESSION_RECORDING_KMS_ENDPOINT'
        | 'SESSION_RECORDING_DYNAMODB_ENDPOINT'
        | 'CLICKHOUSE_HOST'
        | 'CLICKHOUSE_DATABASE'
        | 'CLICKHOUSE_USER'
        | 'CLICKHOUSE_PASSWORD'
        | 'CLICKHOUSE_PASSWORD_FILE'
        | 'CLICKHOUSE_SECURE'
    > &
    Pick<
        SessionRecordingConfig,
        | 'SESSION_RECORDING_V2_S3_REGION'
        | 'SESSION_RECORDING_V2_S3_ENDPOINT'
        | 'SESSION_RECORDING_V2_S3_ACCESS_KEY_ID'
        | 'SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY'
        | 'SESSION_RECORDING_V2_S3_BUCKET'
        | 'SESSION_RECORDING_V2_S3_PREFIX'
    > &
    RecordingApiAuthConfig &
    RecordingApiBlocksConfig

/**
 * Recording API outputs — topic and producer routing per output. All keys
 * follow the `RECORDING_API_OUTPUT_*` convention. Topic values default to
 * the same Kafka topics the session-replay ingestion consumer writes to,
 * since recording-api emits deletion tombstones into the same streams.
 */
export type RecordingApiOutputsConfig = {
    RECORDING_API_OUTPUT_REPLAY_EVENTS_TOPIC: string
    RECORDING_API_OUTPUT_REPLAY_EVENTS_PRODUCER: RecordingApiProducerName

    RECORDING_API_OUTPUT_SESSION_FEATURES_TOPIC: string
    RECORDING_API_OUTPUT_SESSION_FEATURES_PRODUCER: RecordingApiProducerName
}

export function getDefaultRecordingApiOutputsConfig(): RecordingApiOutputsConfig {
    return {
        RECORDING_API_OUTPUT_REPLAY_EVENTS_TOPIC: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
        RECORDING_API_OUTPUT_REPLAY_EVENTS_PRODUCER: INGESTION_SESSIONREPLAY_PRODUCER,
        RECORDING_API_OUTPUT_SESSION_FEATURES_TOPIC: KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
        RECORDING_API_OUTPUT_SESSION_FEATURES_PRODUCER: INGESTION_SESSIONREPLAY_PRODUCER,
    }
}

export interface RecordingBlock {
    key: string
    start_byte: number
    end_byte: number
    start_timestamp: string
    end_timestamp: string
}
