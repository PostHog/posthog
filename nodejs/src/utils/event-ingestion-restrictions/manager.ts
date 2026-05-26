import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { BackgroundRefresher } from '../background-refresher'
import { parseJSON } from '../json-parse'
import { logger } from '../logger'
import { REDIS_KEY_PREFIX, RedisRestrictionArraySchema, RedisRestrictionType, toRestrictionRule } from './redis-schema'
import { EventContext, RestrictionFilters, RestrictionMap, RestrictionRule, RestrictionType } from './rules'

export type IngestionPipeline = 'analytics' | 'session_recordings' | 'errortracking' | 'clientwarnings'

const EMPTY_RESTRICTIONS: ReadonlySet<RestrictionType> = new Set()

export interface EventIngestionRestrictionManagerOptions {
    pipeline?: IngestionPipeline
    staticDropEventTokens?: string[]
    staticSkipPersonTokens?: string[]
    staticForceOverflowTokens?: string[]
    staticRedirectToDlqTokens?: string[]
}

/*
 * Events can be restricted for ingestion through static and dynamic configs.
 * This manager handles the loading/caching/refreshing of the dynamic configs
 * then coalesces the logic for restricting events between the two types of configs.
 *
 * Restriction types are:
 * - DROP_EVENT: Drop events from ingestion
 * - SKIP_PERSON_PROCESSING: Skip person processing
 * - FORCE_OVERFLOW: Force overflow from ingestion
 * - REDIRECT_TO_DLQ: Redirect events to dead letter queue
 *
 * Filter logic (matching Rust implementation):
 * - AND between filter types (distinct_ids AND session_ids AND event_names AND event_uuids)
 * - OR within each filter type (value in set)
 * - Empty filter = matches all (neutral in AND)
 *
 * Constructed by `EventIngestionRestrictionManagerScope.start()` with a
 * primed background refresher; the class itself has no lifecycle methods.
 */
export class EventIngestionRestrictionManager {
    constructor(
        private readonly staticRestrictionMap: RestrictionMap,
        private readonly dynamicConfigRefresher: BackgroundRefresher<RestrictionMap>
    ) {}

    async forceRefresh(): Promise<void> {
        await this.dynamicConfigRefresher.refresh()
    }

    // Pass headers directly - no need to construct a new object
    getAppliedRestrictions(token?: string, headers?: EventContext): ReadonlySet<RestrictionType> {
        if (!token) {
            return EMPTY_RESTRICTIONS
        }
        const restrictionMap = this.dynamicConfigRefresher.tryGet() ?? this.staticRestrictionMap
        return restrictionMap.getRestrictions(token, headers)
    }
}

/**
 * Lifecycle owner for `EventIngestionRestrictionManager`. `start()` builds
 * the static restriction map from the supplied options, sets up the
 * background refresher that fetches dynamic config from Redis, primes the
 * cache, and constructs the manager with everything ready. The returned
 * manager has no lifecycle of its own.
 */
export class EventIngestionRestrictionManagerScope {
    constructor(
        private readonly redisPool: GenericPool<Redis>,
        private readonly options: EventIngestionRestrictionManagerOptions = {}
    ) {}

    async start(): Promise<{ value: EventIngestionRestrictionManager; stop: () => Promise<void> }> {
        const {
            pipeline = 'analytics',
            staticDropEventTokens = [],
            staticSkipPersonTokens = [],
            staticForceOverflowTokens = [],
            staticRedirectToDlqTokens = [],
        } = this.options

        const staticRestrictionMap = new RestrictionMap()
        addStaticRestrictions(staticRestrictionMap, RestrictionType.DROP_EVENT, staticDropEventTokens)
        addStaticRestrictions(staticRestrictionMap, RestrictionType.SKIP_PERSON_PROCESSING, staticSkipPersonTokens)
        addStaticRestrictions(staticRestrictionMap, RestrictionType.FORCE_OVERFLOW, staticForceOverflowTokens)
        addStaticRestrictions(staticRestrictionMap, RestrictionType.REDIRECT_TO_DLQ, staticRedirectToDlqTokens)

        const redisPool = this.redisPool
        const dynamicConfigRefresher = new BackgroundRefresher(async () => {
            logger.debug('🔁', 'ingestion_event_restriction_manager - refreshing dynamic config in the background')
            const manager = new RestrictionMap()
            manager.merge(staticRestrictionMap)
            const dynamicRules = await fetchDynamicRestrictionsFromRedis(redisPool, pipeline)
            for (const { token, rule } of dynamicRules) {
                manager.addRestriction(token, rule)
            }
            return manager
        })

        // Prime the dynamic config cache. Failures are logged but don't block
        // start — static restrictions still apply, and `tryGet` will retry in
        // the background on subsequent reads.
        await dynamicConfigRefresher.get().catch((error) => {
            logger.error('Failed to initialize event ingestion restriction config', { error })
        })

        return {
            value: new EventIngestionRestrictionManager(staticRestrictionMap, dynamicConfigRefresher),
            stop: () => Promise.resolve(),
        }
    }
}

function addStaticRestrictions(map: RestrictionMap, restrictionType: RestrictionType, entries: string[]): void {
    for (const entry of entries) {
        // Static config supports: token, token:distinct_id (legacy), token:distinct_id:value
        if (entry.includes(':distinct_id:')) {
            const [token, , distinctId] = entry.split(':')
            const filters = new RestrictionFilters({ distinctIds: [distinctId] })
            map.addRestriction(token, {
                restrictionType,
                scope: { type: 'filtered', filters },
            })
        } else if (entry.includes(':')) {
            // Legacy format: token:distinct_id
            const [token, distinctId] = entry.split(':')
            const filters = new RestrictionFilters({ distinctIds: [distinctId] })
            map.addRestriction(token, {
                restrictionType,
                scope: { type: 'filtered', filters },
            })
        } else {
            map.addRestriction(entry, {
                restrictionType,
                scope: { type: 'all' },
            })
        }
    }
}

async function fetchDynamicRestrictionsFromRedis(
    redisPool: GenericPool<Redis>,
    pipeline: IngestionPipeline
): Promise<{ token: string; rule: RestrictionRule }[]> {
    const rules: { token: string; rule: RestrictionRule }[] = []

    try {
        const redisClient = await redisPool.acquire()
        try {
            const redisPipeline = redisClient.pipeline()
            redisPipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.DROP_EVENT_FROM_INGESTION}`)
            redisPipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.SKIP_PERSON_PROCESSING}`)
            redisPipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.FORCE_OVERFLOW_FROM_INGESTION}`)
            redisPipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.REDIRECT_TO_DLQ}`)
            const [dropResult, skipResult, overflowResult, dlqResult] = await redisPipeline.exec()

            const processRedisResult = (redisResult: any, restrictionType: RestrictionType) => {
                if (!redisResult?.[1]) {
                    return
                }

                try {
                    const json = parseJSON(redisResult[1] as string)
                    const parseResult = RedisRestrictionArraySchema.safeParse(json)

                    if (!parseResult.success) {
                        logger.warn(`Failed to parse Redis restriction config for ${restrictionType}`, {
                            error: parseResult.error,
                        })
                        return
                    }

                    for (const item of parseResult.data) {
                        if (!item.pipelines || !item.pipelines.includes(pipeline)) {
                            continue
                        }

                        const rule = toRestrictionRule(item, restrictionType)
                        rules.push({ token: item.token, rule })
                    }
                } catch (error) {
                    logger.warn(`Failed to parse JSON for ${restrictionType}`, { error })
                }
            }

            processRedisResult(dropResult, RestrictionType.DROP_EVENT)
            processRedisResult(skipResult, RestrictionType.SKIP_PERSON_PROCESSING)
            processRedisResult(overflowResult, RestrictionType.FORCE_OVERFLOW)
            processRedisResult(dlqResult, RestrictionType.REDIRECT_TO_DLQ)
        } catch (error) {
            logger.warn('Error reading dynamic config for event ingestion restrictions from Redis', { error })
        } finally {
            await redisPool.release(redisClient)
        }
    } catch (error) {
        logger.warn('Error acquiring Redis client from pool for token restrictions', { error })
    }

    return rules
}
