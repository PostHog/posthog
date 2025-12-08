import { Hub } from '../types'
import { BackgroundRefresher } from './background-refresher'
import { parseJSON } from './json-parse'
import { logger } from './logger'

export type EventIngestionRestrictionManagerHub = Pick<
    Hub,
    'USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG' | 'redisPool'
>

export enum RedisRestrictionType {
    DROP_EVENT_FROM_INGESTION = 'drop_event_from_ingestion',
    SKIP_PERSON_PROCESSING = 'skip_person_processing',
    FORCE_OVERFLOW_FROM_INGESTION = 'force_overflow_from_ingestion',
    REDIRECT_TO_DLQ = 'redirect_to_dlq',
}

export enum Restriction {
    DROP_EVENT = 1,
    SKIP_PERSON_PROCESSING = 2,
    FORCE_OVERFLOW = 3,
    REDIRECT_TO_DLQ = 4,
}

export type IngestionPipeline = 'analytics' | 'session_recordings'

export const REDIS_KEY_PREFIX = 'event_ingestion_restriction_dynamic_config'

/*
 *
 * Events can be restricted for ingestion through static and dynamic configs.
 * This manager handles the loading/caching/refreshing of the dynamic configs
 * then coalesces the logic for restricting events between the two types of configs.
 * Restriction types are:
 * - DROP_EVENT: Drop events from ingestion
 * - SKIP_PERSON_PROCESSING: Skip person processing
 * - FORCE_OVERFLOW: Force overflow from ingestion
 * - REDIRECT_TO_DLQ: Redirect events to dead letter queue
 *
 */
export class EventIngestionRestrictionManager {
    private hub: EventIngestionRestrictionManagerHub
    private pipeline: IngestionPipeline
    private staticConfig: Record<Restriction, Set<string>>
    private dynamicConfigRefresher: BackgroundRefresher<Partial<Record<Restriction, Set<string>>>>
    private latestDynamicConfig: Partial<Record<Restriction, Set<string>>> = {}

    constructor(
        hub: EventIngestionRestrictionManagerHub,
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

        this.hub = hub
        this.pipeline = pipeline
        this.staticConfig = {
            [Restriction.DROP_EVENT]: new Set(staticDropEventTokens),
            [Restriction.SKIP_PERSON_PROCESSING]: new Set(staticSkipPersonTokens),
            [Restriction.FORCE_OVERFLOW]: new Set(staticForceOverflowTokens),
            [Restriction.REDIRECT_TO_DLQ]: new Set(staticRedirectToDlqTokens),
        }

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

    async fetchDynamicEventIngestionRestrictionConfig(): Promise<Partial<Record<Restriction, Set<string>>>> {
        if (!this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            return {}
        }

        try {
            const redisClient = await this.hub.redisPool.acquire()
            try {
                const pipeline = redisClient.pipeline()
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.DROP_EVENT_FROM_INGESTION}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.SKIP_PERSON_PROCESSING}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.FORCE_OVERFLOW_FROM_INGESTION}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.REDIRECT_TO_DLQ}`)
                const [dropResult, skipResult, overflowResult, dlqResult] = await pipeline.exec()

                const result: Partial<Record<Restriction, Set<string>>> = {}
                const processRedisResult = (redisResult: any, restriction: Restriction) => {
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
                            result[restriction] = new Set(items)
                        } else {
                            logger.warn(`Expected array for ${restriction} but got different JSON type`)
                            result[restriction] = new Set()
                        }
                    } catch (error) {
                        logger.warn(`Failed to parse JSON for ${restriction}`, { error })
                        result[restriction] = new Set()
                    }
                }

                processRedisResult(dropResult, Restriction.DROP_EVENT)
                processRedisResult(skipResult, Restriction.SKIP_PERSON_PROCESSING)
                processRedisResult(overflowResult, Restriction.FORCE_OVERFLOW)
                processRedisResult(dlqResult, Restriction.REDIRECT_TO_DLQ)
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
        return this.checkRestriction(token, distinctId, sessionId, eventName, eventUuid, Restriction.DROP_EVENT)
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
            Restriction.SKIP_PERSON_PROCESSING
        )
    }

    shouldForceOverflow(
        token?: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): boolean {
        return this.checkRestriction(token, distinctId, sessionId, eventName, eventUuid, Restriction.FORCE_OVERFLOW)
    }

    shouldRedirectToDlq(
        token?: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): boolean {
        return this.checkRestriction(token, distinctId, sessionId, eventName, eventUuid, Restriction.REDIRECT_TO_DLQ)
    }

    getAppliedRestrictions(
        token?: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): Restriction[] {
        const restrictions: Restriction[] = []

        for (const restriction of [
            Restriction.DROP_EVENT,
            Restriction.SKIP_PERSON_PROCESSING,
            Restriction.FORCE_OVERFLOW,
            Restriction.REDIRECT_TO_DLQ,
        ]) {
            if (this.checkRestriction(token, distinctId, sessionId, eventName, eventUuid, restriction)) {
                restrictions.push(restriction)
            }
        }

        return restrictions
    }

    private checkRestriction(
        token: string | undefined,
        distinctId: string | undefined,
        sessionId: string | undefined,
        eventName: string | undefined,
        eventUuid: string | undefined,
        restriction: Restriction
    ): boolean {
        if (!token) {
            return false
        }

        const keys = this.buildLookupKeys(token, distinctId, sessionId, eventName, eventUuid)

        if (this.matchesStaticConfig(token, keys, restriction)) {
            return true
        }

        return this.matchesDynamicConfig(token, keys, restriction)
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

    private matchesStaticConfig(
        token: string,
        keys: {
            tokenDistinctIdKey?: string
            tokenSessionIdKey?: string
            tokenEventNameKey?: string
            tokenEventUuidKey?: string
            tokenDistinctIdKeyLegacy?: string
        },
        restriction: Restriction
    ): boolean {
        const staticList = this.staticConfig[restriction]
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
        restriction: Restriction
    ): boolean {
        if (!this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            return false
        }

        void this.dynamicConfigRefresher.get().catch((error) => {
            logger.warn('Error triggering background refresh for dynamic config', { error })
        })

        const configSet = this.latestDynamicConfig[restriction]
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
