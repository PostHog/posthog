import { Hub } from '../types'
import { BackgroundRefresher } from './background-refresher'
import { logger } from './logger'

export enum RestrictionType {
    DROP_EVENT_FROM_INGESTION = 'drop_event_from_ingestion',
    SKIP_PERSON_PROCESSING = 'skip_person_processing',
    FORCE_OVERFLOW_FROM_INGESTION = 'force_overflow_from_ingestion',
}

const REDIS_KEY_PREFIX = 'event_restriction_dynamic_config'

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
    private staticDropEventList: Set<string>
    private staticSkipPersonList: Set<string>
    private staticForceOverflowList: Set<string>
    private dynamicConfigRefresher: BackgroundRefresher<Partial<Record<string, Set<string>>>>
    private latestDynamicConfig: Partial<Record<RestrictionType, Set<string>>> = {}

    // NICKS TODO: need to clean up options vs hub (and do we need Hub?)
    constructor(
        hub: Hub,
        options: {
            staticDropEventTokens?: string[]
            staticSkipPersonTokens?: string[]
            staticForceOverflowTokens?: string[]
        } = {}
    ) {
        const { staticDropEventTokens = [], staticSkipPersonTokens = [], staticForceOverflowTokens = [] } = options

        this.hub = hub
        this.staticDropEventList = new Set(staticDropEventTokens)
        this.staticSkipPersonList = new Set(staticSkipPersonTokens)
        this.staticForceOverflowList = new Set(staticForceOverflowTokens)

        this.dynamicConfigRefresher = new BackgroundRefresher(async () => {
            try {
                logger.info('🔁', 'token_restriction_manager - refreshing dynamic config in the background')
                const config = await this.fetchDynamicEventIngestionRestrictionConfig()
                this.latestDynamicConfig = config
                return config
            } catch (error) {
                logger.error('token_restriction_manager - error refreshing dynamic config', { error })
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
                if (dropResult?.[1]) {
                    result[RestrictionType.DROP_EVENT_FROM_INGESTION] = new Set(
                        (dropResult[1] as string).split(',').filter(Boolean)
                    )
                }
                if (skipResult?.[1]) {
                    result[RestrictionType.SKIP_PERSON_PROCESSING] = new Set(
                        (skipResult[1] as string).split(',').filter(Boolean)
                    )
                }
                if (overflowResult?.[1]) {
                    result[RestrictionType.FORCE_OVERFLOW_FROM_INGESTION] = new Set(
                        (overflowResult[1] as string).split(',').filter(Boolean)
                    )
                }
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
