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

const EMPTY_RESTRICTIONS: ReadonlySet<Restriction> = new Set()

type RestrictionIdentifier =
    | { type: 'all' }
    | { type: 'distinct_id'; value: string }
    | { type: 'session_id'; value: string }
    | { type: 'event_name'; value: string }
    | { type: 'event_uuid'; value: string }

type TokenRestrictions = {
    all: Set<Restriction>
    distinct_id: Map<string, Set<Restriction>>
    session_id: Map<string, Set<Restriction>>
    event_name: Map<string, Set<Restriction>>
    event_uuid: Map<string, Set<Restriction>>
}

class RestrictionMap {
    private tokens: Map<string, TokenRestrictions> = new Map()

    addRestriction(restriction: Restriction, token: string, identifier: RestrictionIdentifier): void {
        let tokenEntry = this.tokens.get(token)
        if (!tokenEntry) {
            tokenEntry = {
                all: new Set(),
                distinct_id: new Map(),
                session_id: new Map(),
                event_name: new Map(),
                event_uuid: new Map(),
            }
            this.tokens.set(token, tokenEntry)
        }

        if (identifier.type === 'all') {
            tokenEntry.all.add(restriction)
            return
        }

        let restrictionSet = tokenEntry[identifier.type].get(identifier.value)
        if (!restrictionSet) {
            restrictionSet = new Set()
            tokenEntry[identifier.type].set(identifier.value, restrictionSet)
        }
        restrictionSet.add(restriction)
    }

    getRestrictions(
        token: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): ReadonlySet<Restriction> {
        const tokenEntry = this.tokens.get(token)
        if (!tokenEntry) {
            return EMPTY_RESTRICTIONS
        }

        const restrictions = new Set(tokenEntry.all)

        if (distinctId) {
            const r = tokenEntry.distinct_id.get(distinctId)
            if (r) {
                for (const restriction of r) {
                    restrictions.add(restriction)
                }
            }
        }

        if (sessionId) {
            const r = tokenEntry.session_id.get(sessionId)
            if (r) {
                for (const restriction of r) {
                    restrictions.add(restriction)
                }
            }
        }

        if (eventName) {
            const r = tokenEntry.event_name.get(eventName)
            if (r) {
                for (const restriction of r) {
                    restrictions.add(restriction)
                }
            }
        }

        if (eventUuid) {
            const r = tokenEntry.event_uuid.get(eventUuid)
            if (r) {
                for (const restriction of r) {
                    restrictions.add(restriction)
                }
            }
        }

        return restrictions
    }
}

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
type ParsedRestriction = {
    restriction: Restriction
    token: string
    identifier: RestrictionIdentifier
}

export class EventIngestionRestrictionManager {
    private hub: EventIngestionRestrictionManagerHub
    private pipeline: IngestionPipeline
    private staticRestrictions: ParsedRestriction[] = []
    private restrictionMap: RestrictionMap = new RestrictionMap()
    private dynamicConfigRefresher: BackgroundRefresher<void>

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

        this.addStaticRestrictions(Restriction.DROP_EVENT, staticDropEventTokens)
        this.addStaticRestrictions(Restriction.SKIP_PERSON_PROCESSING, staticSkipPersonTokens)
        this.addStaticRestrictions(Restriction.FORCE_OVERFLOW, staticForceOverflowTokens)
        this.addStaticRestrictions(Restriction.REDIRECT_TO_DLQ, staticRedirectToDlqTokens)

        this.dynamicConfigRefresher = new BackgroundRefresher(async () => {
            try {
                logger.info('🔁', 'ingestion_event_restriction_manager - refreshing dynamic config in the background')
                await this.refreshDynamicConfig()
            } catch (error) {
                logger.error('ingestion event restriction manager - error refreshing dynamic config', { error })
            }
        })

        if (this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            void this.dynamicConfigRefresher.get().catch((error) => {
                logger.error('Failed to initialize event ingestion restriction dynamic config', { error })
            })
        }
    }

    async forceRefresh(): Promise<void> {
        if (this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            await this.dynamicConfigRefresher.refresh()
        }
    }

    getAppliedRestrictions(
        token?: string,
        distinctId?: string,
        sessionId?: string,
        eventName?: string,
        eventUuid?: string
    ): ReadonlySet<Restriction> {
        if (!token) {
            return EMPTY_RESTRICTIONS
        }

        if (this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            void this.dynamicConfigRefresher.get().catch((error) => {
                logger.warn('Error triggering background refresh for dynamic config', { error })
            })
        }

        return this.restrictionMap.getRestrictions(token, distinctId, sessionId, eventName, eventUuid)
    }

    private addStaticRestrictions(restriction: Restriction, entries: string[]): void {
        for (const entry of entries) {
            // Static config supports: token, token:distinct_id (legacy), token:distinct_id:value
            let parsed: ParsedRestriction

            if (entry.includes(':distinct_id:')) {
                const [token, , distinctId] = entry.split(':')
                parsed = { restriction, token, identifier: { type: 'distinct_id', value: distinctId } }
            } else if (entry.includes(':')) {
                // Legacy format: token:distinct_id
                const [token, distinctId] = entry.split(':')
                parsed = { restriction, token, identifier: { type: 'distinct_id', value: distinctId } }
            } else {
                parsed = { restriction, token: entry, identifier: { type: 'all' } }
            }

            this.staticRestrictions.push(parsed)
            this.restrictionMap.addRestriction(parsed.restriction, parsed.token, parsed.identifier)
        }
    }

    private async refreshDynamicConfig(): Promise<void> {
        if (!this.hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG) {
            return
        }

        const dynamicRestrictions = await this.fetchDynamicRestrictionsFromRedis()

        // Rebuild the lookup with both static and dynamic restrictions
        const newMap = new RestrictionMap()

        for (const { restriction, token, identifier } of this.staticRestrictions) {
            newMap.addRestriction(restriction, token, identifier)
        }

        for (const { restriction, token, identifier } of dynamicRestrictions) {
            newMap.addRestriction(restriction, token, identifier)
        }

        this.restrictionMap = newMap
    }

    private async fetchDynamicRestrictionsFromRedis(): Promise<ParsedRestriction[]> {
        const restrictions: ParsedRestriction[] = []

        try {
            const redisClient = await this.hub.redisPool.acquire()
            try {
                const pipeline = redisClient.pipeline()
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.DROP_EVENT_FROM_INGESTION}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.SKIP_PERSON_PROCESSING}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.FORCE_OVERFLOW_FROM_INGESTION}`)
                pipeline.get(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.REDIRECT_TO_DLQ}`)
                const [dropResult, skipResult, overflowResult, dlqResult] = await pipeline.exec()

                const processRedisResult = (redisResult: any, restriction: Restriction) => {
                    if (!redisResult?.[1]) {
                        return
                    }

                    try {
                        const parsedArray = parseJSON(redisResult[1] as string)
                        if (Array.isArray(parsedArray)) {
                            for (const item of parsedArray) {
                                if (typeof item === 'string') {
                                    // Old format - ignore
                                    continue
                                }
                                if (typeof item === 'object' && item !== null && 'token' in item) {
                                    const pipelines: unknown = item.pipelines
                                    const appliesToPipeline =
                                        Array.isArray(pipelines) && pipelines.includes(this.pipeline)

                                    if (appliesToPipeline) {
                                        const token = String(item.token)
                                        if ('distinct_id' in item && item.distinct_id) {
                                            restrictions.push({
                                                restriction,
                                                token,
                                                identifier: { type: 'distinct_id', value: String(item.distinct_id) },
                                            })
                                        } else if ('session_id' in item && item.session_id) {
                                            restrictions.push({
                                                restriction,
                                                token,
                                                identifier: { type: 'session_id', value: String(item.session_id) },
                                            })
                                        } else if ('event_name' in item && item.event_name) {
                                            restrictions.push({
                                                restriction,
                                                token,
                                                identifier: { type: 'event_name', value: String(item.event_name) },
                                            })
                                        } else if ('event_uuid' in item && item.event_uuid) {
                                            restrictions.push({
                                                restriction,
                                                token,
                                                identifier: { type: 'event_uuid', value: String(item.event_uuid) },
                                            })
                                        } else {
                                            restrictions.push({ restriction, token, identifier: { type: 'all' } })
                                        }
                                    }
                                }
                            }
                        } else {
                            logger.warn(`Expected array for ${restriction} but got different JSON type`)
                        }
                    } catch (error) {
                        logger.warn(`Failed to parse JSON for ${restriction}`, { error })
                    }
                }

                processRedisResult(dropResult, Restriction.DROP_EVENT)
                processRedisResult(skipResult, Restriction.SKIP_PERSON_PROCESSING)
                processRedisResult(overflowResult, Restriction.FORCE_OVERFLOW)
                processRedisResult(dlqResult, Restriction.REDIRECT_TO_DLQ)
            } catch (error) {
                logger.warn('Error reading dynamic config for event ingestion restrictions from Redis', { error })
            } finally {
                await this.hub.redisPool.release(redisClient)
            }
        } catch (error) {
            logger.warn('Error acquiring Redis client from pool for token restrictions', { error })
        }

        return restrictions
    }
}
