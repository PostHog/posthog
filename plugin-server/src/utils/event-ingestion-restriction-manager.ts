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
                logger.info('🔁', 'ingestion_event_restriction_manager - dynamic config refreshed', { config })
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
                            // New format: [{"token": "token1", "pipelines": ["analytics", "session_recordings"]}, ...]
                            // Old format entries (plain strings) are ignored
                            const items = parsedArray.flatMap((item) => {
                                if (typeof item === 'string') {
                                    // Old format - ignore these entries
                                    return []
                                } else if (typeof item === 'object' && item !== null && 'token' in item) {
                                    // New format - check if this pipeline is in the pipelines array
                                    const pipelines: unknown = item.pipelines
                                    const appliesToPipeline =
                                        Array.isArray(pipelines) && pipelines.includes(this.pipeline)

                                    if (appliesToPipeline) {
                                        if ('distinct_id' in item && item.distinct_id) {
                                            return [`${item.token}:distinct_id:${item.distinct_id}`]
                                        } else if ('session_id' in item && item.session_id) {
                                            return [`${item.token}:session_id:${item.session_id}`]
                                        } else if ('event_name' in item && item.event_name) {
                                            return [`${item.token}:event_name:${item.event_name}`]
                                        } else if ('event_uuid' in item && item.event_uuid) {
                                            return [`${item.token}:event_uuid:${item.event_uuid}`]
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

    shouldDropEvent(
        token?: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): boolean {
        return this.checkRestriction(
            token,
            distinctId,
            sessionId,
            eventName,
            eventUuid,
            this.staticDropEventList,
            RestrictionType.DROP_EVENT_FROM_INGESTION
        )
    }

    shouldSkipPerson(
        token?: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): boolean {
        return this.checkRestriction(
            token,
            distinctId,
            sessionId,
            eventName,
            eventUuid,
            this.staticSkipPersonList,
            RestrictionType.SKIP_PERSON_PROCESSING
        )
    }

    shouldForceOverflow(
        token?: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): boolean {
        return this.checkRestriction(
            token,
            distinctId,
            sessionId,
            eventName,
            eventUuid,
            this.staticForceOverflowList,
            RestrictionType.FORCE_OVERFLOW_FROM_INGESTION
        )
    }

    private checkRestriction(
        token: string | undefined,
        distinctId: string | undefined,
        sessionId: string | undefined,
        eventName: string | undefined,
        eventUuid: string | undefined,
        staticList: Set<string>,
        restrictionType: RestrictionType
    ): boolean {
        if (!token) {
            return false
        }

        const keys = this.buildLookupKeys(token, distinctId, sessionId, eventName, eventUuid)

        if (this.matchesStaticList(token, keys, staticList)) {
            return true
        }

        return this.matchesDynamicConfig(token, keys, restrictionType)
    }

    private buildLookupKeys(
        token: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): {
        tokenDistinctIdKey?: string
        tokenSessionIdKey?: string
        tokenEventNameKey?: string
        tokenEventUuidKey?: string
        tokenDistinctIdKeyLegacy?: string
    } {
        return {
            tokenDistinctIdKey: distinctId ? `${token}:distinct_id:${distinctId}` : undefined,
            tokenSessionIdKey: sessionId ? `${token}:session_id:${sessionId}` : undefined,
            tokenEventNameKey: eventName ? `${token}:event_name:${eventName}` : undefined,
            tokenEventUuidKey: eventUuid ? `${token}:event_uuid:${eventUuid}` : undefined,
            tokenDistinctIdKeyLegacy: distinctId ? `${token}:${distinctId}` : undefined,
        }
    }

    private matchesStaticList(
        token: string,
        keys: {
            tokenDistinctIdKey?: string
            tokenSessionIdKey?: string
            tokenEventNameKey?: string
            tokenEventUuidKey?: string
            tokenDistinctIdKeyLegacy?: string
        },
        staticList: Set<string>
    ): boolean {
        // Static config only supports distinct_id, both old format token:distinct_id and new format token:distinct_id:distinct_id
        return (
            staticList.has(token) ||
            (!!keys.tokenDistinctIdKey && staticList.has(keys.tokenDistinctIdKey)) ||
            (!!keys.tokenDistinctIdKeyLegacy && staticList.has(keys.tokenDistinctIdKeyLegacy))
        )
    }

    private matchesDynamicConfig(
        token: string,
        keys: {
            tokenDistinctIdKey?: string
            tokenSessionIdKey?: string
            tokenEventNameKey?: string
            tokenEventUuidKey?: string
        },
        restrictionType: RestrictionType
    ): boolean {
        if (!this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            return false
        }

        void this.dynamicConfigRefresher.get().catch((error) => {
            logger.warn('Error triggering background refresh for dynamic config', { error })
        })

        const configSet = this.latestDynamicConfig[restrictionType]
        if (!configSet) {
            return false
        }

        return (
            configSet.has(token) ||
            (!!keys.tokenDistinctIdKey && configSet.has(keys.tokenDistinctIdKey)) ||
            (!!keys.tokenSessionIdKey && configSet.has(keys.tokenSessionIdKey)) ||
            (!!keys.tokenEventNameKey && configSet.has(keys.tokenEventNameKey)) ||
            (!!keys.tokenEventUuidKey && configSet.has(keys.tokenEventUuidKey))
        )
    }
}
