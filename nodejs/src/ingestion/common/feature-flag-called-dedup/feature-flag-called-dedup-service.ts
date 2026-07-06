import { createHash } from 'crypto'
import { Redis } from 'ioredis'

import { timeoutGuard } from '~/common/utils/db/utils'
import { parseTeamsList } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { IngestionConsumerConfig, IngestionLane, REALTIME_INGESTION_LANES } from '~/ingestion/config'
import { RedisPool } from '~/types'

import { featureFlagCalledDedupRedisLatency, featureFlagCalledDedupRedisOpsTotal } from './metrics'

// Deliberately terse: at full rollout every key byte costs ~13 MB of shared
// Redis memory (one byte per ~13M live keys).
const REDIS_KEY_PREFIX = 'ffcd:'

// 22 base64url chars = 132 bits. Birthday-bound collision probability across
// ~13M live keys is ~2^-86 — far below the rate of any failure mode we handle.
const HASH_LENGTH = 22

const FEATURE_FLAG_CALLED_DEDUP_MODES = ['disabled', 'shadow', 'drop'] as const

export type FeatureFlagCalledDedupMode = (typeof FEATURE_FLAG_CALLED_DEDUP_MODES)[number]

function isFeatureFlagCalledDedupMode(mode: string): mode is FeatureFlagCalledDedupMode {
    return (FEATURE_FLAG_CALLED_DEDUP_MODES as readonly string[]).includes(mode)
}

export interface FeatureFlagCalledDedupConfig {
    mode: FeatureFlagCalledDedupMode
    /** '*' for all teams, or an explicit allowlist of team IDs. */
    teams: number[] | '*'
    /** Escape hatch: teams never deduped, even when `teams` is '*'. */
    excludedTeams: number[]
    ttlSeconds: number
}

export function parseFeatureFlagCalledDedupConfig(
    mode: string,
    teams: string,
    excludedTeams: string,
    ttlSeconds: number
): FeatureFlagCalledDedupConfig {
    let parsedMode: FeatureFlagCalledDedupMode = 'disabled'
    if (isFeatureFlagCalledDedupMode(mode)) {
        parsedMode = mode
    } else {
        logger.warn('Invalid INGESTION_FEATURE_FLAG_CALLED_DEDUP_MODE, falling back to disabled', { mode })
    }
    const excluded = parseTeamsList(excludedTeams)
    if (excluded === '*') {
        // An operator reaching for '*' as an exclude-everyone switch means "off";
        // the escape hatch on a data-dropping feature must not fail toward dropping.
        logger.warn('INGESTION_FEATURE_FLAG_CALLED_DEDUP_EXCLUDED_TEAMS is "*", disabling dedup')
        parsedMode = 'disabled'
    }
    if (parsedMode !== 'disabled' && (!Number.isFinite(ttlSeconds) || ttlSeconds <= 0)) {
        // An invalid TTL would make every SET ... EX command error, silently
        // disabling dedup behind a stream of Redis errors.
        logger.warn('Invalid INGESTION_FEATURE_FLAG_CALLED_DEDUP_TTL_SECONDS, falling back to disabled', {
            ttlSeconds,
        })
        parsedMode = 'disabled'
    }
    return {
        mode: parsedMode,
        teams: parseTeamsList(teams),
        excludedTeams: excluded === '*' ? [] : excluded,
        ttlSeconds,
    }
}

/**
 * Builds the Redis claim key for one $feature_flag_called exposure.
 *
 * The variable-length components are JSON-encoded as an array before hashing,
 * so a delimiter appearing inside a value (e.g. a distinct_id containing ':')
 * can never collide with another tuple. `$groups` entries are sorted to make
 * the key independent of property ordering.
 */
export function featureFlagCalledDedupKey(
    teamId: number,
    distinctId: string,
    flagKey: string,
    response: unknown,
    groups: unknown,
    hasExperiment: unknown
): string {
    const normalizedGroups =
        groups && typeof groups === 'object' && !Array.isArray(groups)
            ? Object.entries(groups as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
            : null
    // teamId is also in the hash so the digest alone is tenant-scoped, even if
    // a future code path assembles a key without the prefix. The plaintext
    // teamId stays in the key so operators can SCAN or purge one team's claims.
    const hash = createHash('sha256')
        .update(
            JSON.stringify([
                teamId,
                distinctId,
                flagKey,
                response ?? null,
                normalizedGroups,
                hasExperiment === true ? true : null,
            ])
        )
        .digest('base64url')
        .slice(0, HASH_LENGTH)
    return `${REDIS_KEY_PREFIX}${teamId}:${hash}`
}

/** One keep-first claim for a $feature_flag_called exposure. */
export interface FeatureFlagCalledDedupClaim {
    key: string
    /**
     * Stable identity of the claiming event (its uuid). At-least-once Kafka
     * delivery can replay a batch whose claims already succeeded but whose
     * events were never written; the claim id lets the replay recognize its
     * own claims instead of dropping those events as duplicates.
     */
    claimId: string
}

/**
 * Keep-first dedup claims for $feature_flag_called events.
 */
export interface FeatureFlagCalledDedupService {
    mode: FeatureFlagCalledDedupMode
    isEnabledForTeam(teamId: number): boolean
    /**
     * Claims each key, returning one boolean per claim: true if the event
     * should pass (first to claim the key, or the key holds this event's own
     * claim id from a prior delivery), false if another event already claimed
     * it (duplicate). Duplicate keys within one call resolve in order — the
     * first occurrence claims, later ones are duplicates.
     */
    claimKeys(claims: FeatureFlagCalledDedupClaim[]): Promise<boolean[]>
}

export interface RedisFeatureFlagCalledDedupServiceOptions {
    redisPool: RedisPool
    config: FeatureFlagCalledDedupConfig
}

export type FeatureFlagCalledDedupEnvConfig = Pick<
    IngestionConsumerConfig,
    | 'INGESTION_LANE'
    | 'INGESTION_FEATURE_FLAG_CALLED_DEDUP_MODE'
    | 'INGESTION_FEATURE_FLAG_CALLED_DEDUP_TEAMS'
    | 'INGESTION_FEATURE_FLAG_CALLED_DEDUP_EXCLUDED_TEAMS'
    | 'INGESTION_FEATURE_FLAG_CALLED_DEDUP_TTL_SECONDS'
>

/**
 * Lanes that may dedup: the real-time lanes plus `null` for local dev, where
 * no lane is set. Derived from REALTIME_INGESTION_LANES so a new real-time
 * lane is covered automatically; delayed lanes are excluded by construction.
 * See `createFeatureFlagCalledDedupService` for why delayed lanes must never
 * dedup.
 */
const DEDUP_ALLOWED_LANES: readonly (IngestionLane | null)[] = [...REALTIME_INGESTION_LANES, null]

/**
 * Builds the dedup service from ingestion config, or undefined when the dedup
 * is disabled (the pipeline step treats an absent service as a passthrough).
 *
 * The dedup window is processing-time, not event-time, so lanes that process
 * delayed events (historical, async) must never dedup: a backfilled event is
 * not a duplicate of the live event that claimed its tuple an hour ago. The
 * real-time lanes in DEDUP_ALLOWED_LANES all share that processing-time
 * window, so they may dedup. The lane gate holds even if the dedup env vars
 * leak into a shared config.
 */
export function createFeatureFlagCalledDedupService(
    redisPool: RedisPool,
    envConfig: FeatureFlagCalledDedupEnvConfig
): FeatureFlagCalledDedupService | undefined {
    const config = parseFeatureFlagCalledDedupConfig(
        envConfig.INGESTION_FEATURE_FLAG_CALLED_DEDUP_MODE,
        envConfig.INGESTION_FEATURE_FLAG_CALLED_DEDUP_TEAMS,
        envConfig.INGESTION_FEATURE_FLAG_CALLED_DEDUP_EXCLUDED_TEAMS,
        envConfig.INGESTION_FEATURE_FLAG_CALLED_DEDUP_TTL_SECONDS
    )
    if (config.mode === 'disabled') {
        return undefined
    }
    if (!DEDUP_ALLOWED_LANES.includes(envConfig.INGESTION_LANE)) {
        logger.warn('Feature flag called dedup is not supported on this ingestion lane, disabling', {
            lane: envConfig.INGESTION_LANE,
        })
        return undefined
    }
    return new RedisFeatureFlagCalledDedupService({ redisPool, config })
}

/**
 * Redis-backed keep-first claims: `SET key <claimId> NX EX ttl` paired with a
 * `GET`. The first event for a tuple wins the claim; a later event passes only
 * when the stored claim id is its own (the same event redelivered by Kafka),
 * otherwise it loses the claim for the TTL window.
 *
 * Redis failures that reject fail open (everything is treated as claimed) — a
 * dedup outage must never suppress events. Connectivity loss does not reject:
 * pool clients use `maxRetriesPerRequest: -1`, so commands queue until the
 * shared client error watchdog kills the process; the 30s timeoutGuard below
 * logs and captures an exception but does not abort the command.
 */
export class RedisFeatureFlagCalledDedupService implements FeatureFlagCalledDedupService {
    private redisPool: RedisPool
    private config: FeatureFlagCalledDedupConfig
    private teams: Set<number> | '*'
    private excludedTeams: Set<number>

    constructor(options: RedisFeatureFlagCalledDedupServiceOptions) {
        this.redisPool = options.redisPool
        this.config = options.config
        this.teams = options.config.teams === '*' ? '*' : new Set(options.config.teams)
        this.excludedTeams = new Set(options.config.excludedTeams)
    }

    get mode(): FeatureFlagCalledDedupMode {
        return this.config.mode
    }

    isEnabledForTeam(teamId: number): boolean {
        if (this.excludedTeams.has(teamId)) {
            return false
        }
        return this.teams === '*' || this.teams.has(teamId)
    }

    async claimKeys(claims: FeatureFlagCalledDedupClaim[]): Promise<boolean[]> {
        if (claims.length === 0) {
            return []
        }

        const failOpen = claims.map(() => true)
        const startTime = performance.now()
        const timeout = timeoutGuard('Feature flag called dedup claim delayed. Waiting over 30 sec.', {
            count: claims.length,
        })
        let client: Redis | undefined
        try {
            client = await this.redisPool.acquire()
            const pipeline = client.pipeline()
            for (const claim of claims) {
                pipeline.set(claim.key, claim.claimId, 'EX', this.config.ttlSeconds, 'NX')
                pipeline.get(claim.key)
            }
            const results = await pipeline.exec()
            if (!results || results.length !== claims.length * 2) {
                featureFlagCalledDedupRedisOpsTotal.labels('error').inc()
                return failOpen
            }
            // SET ... NX replies 'OK' when the key was set (claimed) and null
            // when it already existed; the paired GET then tells us whether
            // the existing claim is this event's own (a redelivery). Any
            // per-command error fails open.
            let hadCommandError = false
            const passes = claims.map((claim, index) => {
                const [setError, setValue] = results[index * 2]
                const [getError, getValue] = results[index * 2 + 1]
                if (setError !== null || getError !== null) {
                    hadCommandError = true
                }
                if (setError !== null || setValue === 'OK') {
                    return true
                }
                if (getError !== null) {
                    return true
                }
                // A pipeline is not atomic: the key can expire or be evicted
                // between the SET and the GET. No claim present means no
                // evidence of a duplicate, so fail open.
                return getValue === null || getValue === claim.claimId
            })
            featureFlagCalledDedupRedisOpsTotal.labels(hadCommandError ? 'partial_error' : 'success').inc()
            return passes
        } catch (error) {
            logger.warn('Redis error in feature flag called dedup claim, failing open', { error })
            featureFlagCalledDedupRedisOpsTotal.labels('error').inc()
            return failOpen
        } finally {
            clearTimeout(timeout)
            featureFlagCalledDedupRedisLatency.observe((performance.now() - startTime) / 1000)
            if (client) {
                try {
                    await this.redisPool.release(client)
                } catch (releaseError) {
                    logger.warn('Failed to release Redis client', { error: releaseError })
                }
            }
        }
    }
}
