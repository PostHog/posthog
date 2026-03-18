import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { BackgroundRefresher } from '../background-refresher'
import { parseJSON } from '../json-parse'
import { logger } from '../logger'
import { REDIS_KEY_PREFIX, RedisRestrictionArraySchema, RedisRestrictionType, toRestrictionRule } from './redis-schema'
import { EventContext, RestrictionFilters, RestrictionMap, RestrictionRule, RestrictionType } from './rules'

export type IngestionPipeline = 'analytics' | 'session_recordings'

const EMPTY_RESTRICTIONS: ReadonlySet<RestrictionType> = new Set()

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
 */
export class EventIngestionRestrictionManager {
    private redisPool: GenericPool<Redis>
    private pipeline: IngestionPipeline
    private staticRestrictionMap: RestrictionMap = new RestrictionMap()
    private dynamicConfigRefresher: BackgroundRefresher<RestrictionMap>

    constructor(
        redisPool: GenericPool<Redis>,
        options: {
            pipeline?: IngestionPipeline
            staticDropEventTokens?: string[]
            staticSkipPersonTokens?: string[]
            staticForceOverflowTokens?: string[]
            staticRedirectToDlqTokens?: string[]
        } = {}
    ) {
        const {
            pipeline = 'analytics',
            staticDropEventTokens = [],
            staticSkipPersonTokens = [],
            staticForceOverflowTokens = [],
            staticRedirectToDlqTokens = [],
        } = options

        this.redisPool = redisPool
        this.pipeline = pipeline

        this.addStaticRestrictions(RestrictionType.DROP_EVENT, staticDropEventTokens)
        this.addStaticRestrictions(RestrictionType.SKIP_PERSON_PROCESSING, staticSkipPersonTokens)
        this.addStaticRestrictions(RestrictionType.FORCE_OVERFLOW, staticForceOverflowTokens)
        this.addStaticRestrictions(RestrictionType.REDIRECT_TO_DLQ, staticRedirectToDlqTokens)

        this.dynamicConfigRefresher = new BackgroundRefresher(async () => {
            logger.debug('🔁', 'ingestion_event_restriction_manager - refreshing dynamic config in the background')
            return await this.buildRestrictionMap()
        })

        // Initialize the restriction manager (includes static restrictions)
        void this.dynamicConfigRefresher.get().catch((error) => {
            logger.error('Failed to initialize event ingestion restriction config', { error })
        })
    }

    async forceRefresh(): Promise<void> {
        await this.dynamicConfigRefresher.refresh()
    }

    // Pass headers directly - no need to construct a new object
    getAppliedRestrictions(token?: string, headers?: EventContext): ReadonlySet<RestrictionType> {
        if (!token) {
            return EMPTY_RESTRICTIONS
        }
        const restrictionManager = this.dynamicConfigRefresher.tryGet() ?? this.staticRestrictionMap
        return restrictionManager.getRestrictions(token, headers)
    }

    private addStaticRestrictions(restrictionType: RestrictionType, entries: string[]): void {
        for (const entry of entries) {
            // Static config supports: token, token:distinct_id (legacy), token:distinct_id:value
            if (entry.includes(':distinct_id:')) {
                const [token, , distinctId] = entry.split(':')
                const filters = new RestrictionFilters({ distinctIds: [distinctId] })
                this.staticRestrictionMap.addRestriction(token, {
                    restrictionType,
                    scope: { type: 'filtered', filters },
                })
            } else if (entry.includes(':')) {
                // Legacy format: token:distinct_id
                const [token, distinctId] = entry.split(':')
                const filters = new RestrictionFilters({ distinctIds: [distinctId] })
                this.staticRestrictionMap.addRestriction(token, {
                    restrictionType,
                    scope: { type: 'filtered', filters },
                })
            } else {
                this.staticRestrictionMap.addRestriction(entry, {
                    restrictionType,
                    scope: { type: 'all' },
                })
            }
        }
    }

    private async buildRestrictionMap(): Promise<RestrictionMap> {
        const manager = new RestrictionMap()
        manager.merge(this.staticRestrictionMap)

        const dynamicRules = await this.fetchDynamicRestrictionsFromRedis()
        for (const { token, rule } of dynamicRules) {
            manager.addRestriction(token, rule)
        }

        return manager
    }

    private async fetchDynamicRestrictionsFromRedis(): Promise<{ token: string; rule: RestrictionRule }[]> {
        const rules: { token: string; rule: RestrictionRule }[] = []

        try {
            const redisClient = await this.redisPool.acquire()
            try {
                const pipeline = redisClient.pipeline()
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.DROP_EVENT_FROM_INGESTION}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.SKIP_PERSON_PROCESSING}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.FORCE_OVERFLOW_FROM_INGESTION}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.REDIRECT_TO_DLQ}`)
                const [dropResult, skipResult, overflowResult, dlqResult] = await pipeline.exec()

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
                            if (!item.pipelines || !item.pipelines.includes(this.pipeline)) {
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
                await this.redisPool.release(redisClient)
            }
        } catch (error) {
            logger.warn('Error acquiring Redis client from pool for token restrictions', { error })
        }

        return rules
    }
}
