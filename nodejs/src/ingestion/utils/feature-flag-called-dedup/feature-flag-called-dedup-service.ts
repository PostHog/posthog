import { createHash } from 'crypto'

import { RedisPool } from '../../../types'
import { timeoutGuard } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { parseTeamsList } from '../../event-processing/split-ai-events-step'
import { featureFlagCalledDedupRedisLatency, featureFlagCalledDedupRedisOpsTotal } from './metrics'

const REDIS_KEY_PREFIX = '@posthog/ff-called-dedup/'

export type FeatureFlagCalledDedupMode = 'disabled' | 'shadow' | 'drop'

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
    if (mode !== 'disabled' && mode !== 'shadow' && mode !== 'drop') {
        logger.warn('Invalid INGESTION_FEATURE_FLAG_CALLED_DEDUP_MODE, falling back to disabled', { mode })
        mode = 'disabled'
    }
    const excluded = parseTeamsList(excludedTeams)
    return {
        mode: mode as FeatureFlagCalledDedupMode,
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
    groups: unknown
): string {
    const normalizedGroups =
        groups && typeof groups === 'object' && !Array.isArray(groups)
            ? Object.entries(groups as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
            : null
    const hash = createHash('sha256')
        .update(JSON.stringify([distinctId, flagKey, response ?? null, normalizedGroups]))
        .digest('base64url')
    return `${REDIS_KEY_PREFIX}${teamId}:${hash}`
}

/**
 * Keep-first dedup claims for $feature_flag_called events.
 */
export interface FeatureFlagCalledDedupService {
    mode: FeatureFlagCalledDedupMode
    isEnabledForTeam(teamId: number): boolean
    /**
     * Claims each key, returning one boolean per key: true if this caller is
     * the first to claim it (the event should pass), false if it was already
     * claimed (duplicate). Duplicate keys within one call resolve in order —
     * the first occurrence claims, later ones are duplicates.
     */
    claimKeys(keys: string[]): Promise<boolean[]>
}

export interface RedisFeatureFlagCalledDedupServiceOptions {
    redisPool: RedisPool
    config: FeatureFlagCalledDedupConfig
}

export interface FeatureFlagCalledDedupEnvConfig {
    INGESTION_FEATURE_FLAG_CALLED_DEDUP_MODE: string
    INGESTION_FEATURE_FLAG_CALLED_DEDUP_TEAMS: string
    INGESTION_FEATURE_FLAG_CALLED_DEDUP_EXCLUDED_TEAMS: string
    INGESTION_FEATURE_FLAG_CALLED_DEDUP_TTL_SECONDS: number
}

/**
 * Builds the dedup service from ingestion config, or undefined when the dedup
 * is disabled (the pipeline step treats an absent service as a passthrough).
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
    return new RedisFeatureFlagCalledDedupService({ redisPool, config })
}

/**
 * Redis-backed keep-first claims: `SET key 1 NX EX ttl`. The first event for a
 * tuple wins the claim, every later event within the TTL window loses it. All
 * Redis failures fail open (everything is treated as claimed) — a dedup outage
 * must never suppress events.
 */
export class RedisFeatureFlagCalledDedupService implements FeatureFlagCalledDedupService {
    private redisPool: RedisPool
    private config: FeatureFlagCalledDedupConfig

    constructor(options: RedisFeatureFlagCalledDedupServiceOptions) {
        this.redisPool = options.redisPool
        this.config = options.config
    }

    get mode(): FeatureFlagCalledDedupMode {
        return this.config.mode
    }

    isEnabledForTeam(teamId: number): boolean {
        if (this.config.excludedTeams.includes(teamId)) {
            return false
        }
        return this.config.teams === '*' || this.config.teams.includes(teamId)
    }

    async claimKeys(keys: string[]): Promise<boolean[]> {
        if (keys.length === 0) {
            return []
        }

        const failOpen = keys.map(() => true)
        const startTime = performance.now()
        const timeout = timeoutGuard('Feature flag called dedup claim delayed. Waiting over 30 sec.', {
            count: keys.length,
        })
        let client
        try {
            client = await this.redisPool.acquire()
            const pipeline = client.pipeline()
            for (const key of keys) {
                pipeline.set(key, '1', 'EX', this.config.ttlSeconds, 'NX')
            }
            const results = await pipeline.exec()
            if (!results || results.length !== keys.length) {
                featureFlagCalledDedupRedisOpsTotal.labels('error').inc()
                return failOpen
            }
            featureFlagCalledDedupRedisOpsTotal.labels('success').inc()
            // SET ... NX replies 'OK' when the key was set (claimed) and null
            // when it already existed. A per-command error also fails open.
            return results.map(([err, value]) => err !== null || value === 'OK')
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
