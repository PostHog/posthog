import { Hub } from '../types'
import { BackgroundRefresher } from './background-refresher'
import { parseJSON } from './json-parse'
import { logger } from './logger'

export enum RestrictionType {
    DROP_EVENT_FROM_INGESTION = 'drop_event_from_ingestion',
    SKIP_PERSON_PROCESSING = 'skip_person_processing',
    FORCE_OVERFLOW_FROM_INGESTION = 'force_overflow_from_ingestion',
}

export type IngestionPipeline = 'analytics' | 'session_recordings'

export const REDIS_KEY_PREFIX = 'event_ingestion_restriction_dynamic_config'

/*
 *
 * Events can be restricted for ingestion through static and dynamic configs.
 * This manager handles the loading/caching/refreshing of the dynamic configs
 * then coalesces the logic for restricting events between the two types of configs.
 * Restriction types are:
 * - DROP_EVENT_FROM_INGESTION: Drop events from ingestion
 * - SKIP_PERSON_PROCESSING: Skip person processing
 * - FORCE_OVERFLOW_FROM_INGESTION: Force overflow from ingestion
 *
 */
export class EventIngestionRestrictionManager {
    private hub: Hub
    private pipeline: IngestionPipeline
    private staticDropEventList: Set<string>
    private staticSkipPersonList: Set<string>
    private staticForceOverflowList: Set<string>
    private dynamicConfigRefresher: BackgroundRefresher<Partial<Record<string, Set<string>>>>
    private latestDynamicConfig: Partial<Record<RestrictionType, Set<string>>> = {}

    constructor(
        hub: Hub,
        options: {
            pipeline?: IngestionPipeline
            staticDropEventTokens?: string[]
            staticSkipPersonTokens?: string[]
            staticForceOverflowTokens?: string[]
        } = {}
    ) {
        const {
            pipeline = 'analytics',
            staticDropEventTokens = [],
            staticSkipPersonTokens = [],
            staticForceOverflowTokens = [],
        } = options

        this.hub = hub
        this.pipeline = pipeline
        this.staticDropEventList = new Set(staticDropEventTokens)
        this.staticSkipPersonList = new Set(staticSkipPersonTokens)
        this.staticForceOverflowList = new Set(staticForceOverflowTokens)

        this.dynamicConfigRefresher = new BackgroundRefresher(async () => {
            try {
                logger.info('🔁', 'ingestion_event_restriction_manager - refreshing dynamic config in the background')
                const config = await this.fetchDynamicEventIngestionRestrictionConfig()
                this.latestDynamicConfig = config
                return config
            } catch (error) {
                logger.error('ingestion event restriction manager - error refreshing dynamic config', { error })
                return {}
            }
        })

        if (this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            void this.dynamicConfigRefresher.get().catch((error) => {
                logger.error('Failed to initialize event ingestion restriction dynamic config', { error })
            })
        }
    }

    async fetchDynamicEventIngestionRestrictionConfig(): Promise<Partial<Record<RestrictionType, Set<string>>>> {
        if (!this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            return {}
        }

        try {
            const redisClient = await this.hub.redisPool.acquire()
            try {
                const pipeline = redisClient.pipeline()
                pipeline.get(`${REDIS_KEY_PREFIX}:${RestrictionType.DROP_EVENT_FROM_INGESTION}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RestrictionType.SKIP_PERSON_PROCESSING}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RestrictionType.FORCE_OVERFLOW_FROM_INGESTION}`)
                const [dropResult, skipResult, overflowResult] = await pipeline.exec()

                const result: Partial<Record<RestrictionType, Set<string>>> = {}
                const processRedisResult = (redisResult: any, restrictionType: RestrictionType) => {
                    if (!redisResult?.[1]) {
                        return
                    }

                    try {
                        const parsedArray = parseJSON(redisResult[1] as string)
                        if (Array.isArray(parsedArray)) {
                            // Convert array items to strings
                            // Old format: ["token1", "token2:distinct_id"]
                            // New format: [{"token": "token1", "pipelines": ["analytics", "session_recordings"]}, ...]
                            const items = parsedArray.flatMap((item) => {
                                if (typeof item === 'string') {
                                    // Old format - assume applies to analytics only for backwards compatibility
                                    if (this.pipeline === 'analytics') {
                                        return [item]
                                    }
                                    return []
                                } else if (typeof item === 'object' && item !== null && 'token' in item) {
                                    // New format - check if this pipeline is in the pipelines array
                                    const pipelines: unknown = item.pipelines
                                    const appliesToPipeline =
                                        Array.isArray(pipelines) && pipelines.includes(this.pipeline)

                                    if (appliesToPipeline) {
                                        if ('distinct_id' in item && item.distinct_id) {
                                            return [`${item.token}:${item.distinct_id}`]
                                        } else {
                                            return [item.token]
                                        }
                                    }
                                    return []
                                }
                                return []
                            })
                            result[restrictionType] = new Set(items)
                        } else {
                            logger.warn(`Expected array for ${restrictionType} but got different JSON type`)
                            result[restrictionType] = new Set()
                        }
                    } catch (error) {
                        logger.warn(`Failed to parse JSON for ${restrictionType}`, { error })
                        result[restrictionType] = new Set()
                    }
                }

                processRedisResult(dropResult, RestrictionType.DROP_EVENT_FROM_INGESTION)
                processRedisResult(skipResult, RestrictionType.SKIP_PERSON_PROCESSING)
                processRedisResult(overflowResult, RestrictionType.FORCE_OVERFLOW_FROM_INGESTION)
                return result
            } catch (error) {
                logger.warn('Error reading dynamic config for event ingestion restrictions from Redis', { error })
                return {}
            } finally {
                await this.hub.redisPool.release(redisClient)
            }
        } catch (error) {
            logger.warn('Error acquiring Redis client from pool for token restrictions', { error })
            return {}
        }
    }

    shouldDropEvent(token?: string, distinctId?: string): boolean {
        if (!token) {
            return false
        }

        const tokenDistinctIdKey = distinctId ? `${token}:${distinctId}` : undefined
        if (
            this.staticDropEventList.has(token) ||
            (tokenDistinctIdKey && this.staticDropEventList.has(tokenDistinctIdKey))
        ) {
            return true
        }

        if (!this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            return false
        }

        void this.dynamicConfigRefresher.get().catch((error) => {
            logger.warn('Error triggering background refresh for dynamic config', { error })
        })

        const dropSet = this.latestDynamicConfig[RestrictionType.DROP_EVENT_FROM_INGESTION]

        if (!dropSet) {
            return false
        }
        return dropSet.has(token) || (!!tokenDistinctIdKey && dropSet.has(tokenDistinctIdKey))
    }

    shouldSkipPerson(token?: string, distinctId?: string): boolean {
        if (!token) {
            return false
        }

        const tokenDistinctIdKey = distinctId ? `${token}:${distinctId}` : undefined
        if (
            this.staticSkipPersonList.has(token) ||
            (tokenDistinctIdKey && this.staticSkipPersonList.has(tokenDistinctIdKey))
        ) {
            return true
        }

        if (!this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            return false
        }

        void this.dynamicConfigRefresher.get().catch((error) => {
            logger.warn('Error triggering background refresh for dynamic config', { error })
        })

        const dropSet = this.latestDynamicConfig[RestrictionType.SKIP_PERSON_PROCESSING]

        if (!dropSet) {
            return false
        }
        return dropSet.has(token) || (!!tokenDistinctIdKey && dropSet.has(tokenDistinctIdKey))
    }

    shouldForceOverflow(token?: string, distinctId?: string): boolean {
        if (!token) {
            return false
        }

        const tokenDistinctIdKey = distinctId ? `${token}:${distinctId}` : undefined
        if (
            this.staticForceOverflowList.has(token) ||
            (tokenDistinctIdKey && this.staticForceOverflowList.has(tokenDistinctIdKey))
        ) {
            return true
        }

        if (!this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            return false
        }

        void this.dynamicConfigRefresher.get().catch((error) => {
            logger.warn('Error triggering background refresh for dynamic config', { error })
        })

        const dropSet = this.latestDynamicConfig[RestrictionType.FORCE_OVERFLOW_FROM_INGESTION]

        if (!dropSet) {
            return false
        }
        return dropSet.has(token) || (!!tokenDistinctIdKey && dropSet.has(tokenDistinctIdKey))
    }
}
