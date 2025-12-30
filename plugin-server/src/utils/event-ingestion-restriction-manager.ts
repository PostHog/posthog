import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'
import { z } from 'zod'

import { BackgroundRefresher } from './background-refresher'
import { parseJSON } from './json-parse'
import { logger } from './logger'

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

const IDENTIFIER_TYPES = ['distinct_id', 'session_id', 'event', 'uuid'] as const
type IdentifierType = (typeof IDENTIFIER_TYPES)[number]

export type RestrictionLookup = Partial<Record<IdentifierType, string>>

type RestrictionIdentifier = { type: 'all' } | { type: IdentifierType; value: string }

const RedisRestrictionItemSchema = z
    .object({
        token: z.string(),
        pipelines: z.array(z.enum(['analytics', 'session_recordings'])).optional(),
        distinct_id: z.string().optional(),
        session_id: z.string().optional(),
        event_name: z.string().optional(),
        event_uuid: z.string().optional(),
    })
    .transform((item): { token: string; pipelines?: IngestionPipeline[]; identifier: RestrictionIdentifier } => {
        if (item.distinct_id) {
            return {
                token: item.token,
                pipelines: item.pipelines,
                identifier: { type: 'distinct_id', value: item.distinct_id },
            }
        }
        if (item.session_id) {
            return {
                token: item.token,
                pipelines: item.pipelines,
                identifier: { type: 'session_id', value: item.session_id },
            }
        }
        if (item.event_name) {
            return {
                token: item.token,
                pipelines: item.pipelines,
                identifier: { type: 'event', value: item.event_name },
            }
        }
        if (item.event_uuid) {
            return {
                token: item.token,
                pipelines: item.pipelines,
                identifier: { type: 'uuid', value: item.event_uuid },
            }
        }
        return { token: item.token, pipelines: item.pipelines, identifier: { type: 'all' } }
    })

const RedisRestrictionArraySchema = z.array(RedisRestrictionItemSchema)

type TokenRestrictions = {
    all: Set<Restriction>
    distinct_id: Map<string, Set<Restriction>>
    session_id: Map<string, Set<Restriction>>
    event: Map<string, Set<Restriction>>
    uuid: Map<string, Set<Restriction>>
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
                event: new Map(),
                uuid: new Map(),
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

    getRestrictions(token: string, lookup: RestrictionLookup): ReadonlySet<Restriction> {
        const tokenEntry = this.tokens.get(token)
        if (!tokenEntry) {
            return EMPTY_RESTRICTIONS
        }

        const restrictions = new Set(tokenEntry.all)

        for (const type of IDENTIFIER_TYPES) {
            const value = lookup[type]
            if (value) {
                const r = tokenEntry[type].get(value)
                if (r) {
                    for (const restriction of r) {
                        restrictions.add(restriction)
                    }
                }
            }
        }

        return restrictions
    }

    merge(other: RestrictionMap): void {
        for (const [token, otherEntry] of other.tokens) {
            let tokenEntry = this.tokens.get(token)
            if (!tokenEntry) {
                tokenEntry = {
                    all: new Set(),
                    distinct_id: new Map(),
                    session_id: new Map(),
                    event: new Map(),
                    uuid: new Map(),
                }
                this.tokens.set(token, tokenEntry)
            }

            for (const restriction of otherEntry.all) {
                tokenEntry.all.add(restriction)
            }

            for (const type of IDENTIFIER_TYPES) {
                for (const [value, restrictions] of otherEntry[type]) {
                    let restrictionSet = tokenEntry[type].get(value)
                    if (!restrictionSet) {
                        restrictionSet = new Set()
                        tokenEntry[type].set(value, restrictionSet)
                    }
                    for (const restriction of restrictions) {
                        restrictionSet.add(restriction)
                    }
                }
            }
        }
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

        this.addStaticRestrictions(Restriction.DROP_EVENT, staticDropEventTokens)
        this.addStaticRestrictions(Restriction.SKIP_PERSON_PROCESSING, staticSkipPersonTokens)
        this.addStaticRestrictions(Restriction.FORCE_OVERFLOW, staticForceOverflowTokens)
        this.addStaticRestrictions(Restriction.REDIRECT_TO_DLQ, staticRedirectToDlqTokens)

        this.dynamicConfigRefresher = new BackgroundRefresher(async () => {
            logger.debug('🔁', 'ingestion_event_restriction_manager - refreshing dynamic config in the background')
            return await this.buildRestrictionMap()
        })

        // Initialize the restriction map (includes static restrictions)
        void this.dynamicConfigRefresher.get().catch((error) => {
            logger.error('Failed to initialize event ingestion restriction config', { error })
        })
    }

    async forceRefresh(): Promise<void> {
        await this.dynamicConfigRefresher.refresh()
    }

    getAppliedRestrictions(token?: string, lookup: RestrictionLookup = {}): ReadonlySet<Restriction> {
        if (!token) {
            return EMPTY_RESTRICTIONS
        }

        const restrictionMap = this.dynamicConfigRefresher.tryGet() ?? this.staticRestrictionMap
        return restrictionMap.getRestrictions(token, lookup)
    }

    private addStaticRestrictions(restriction: Restriction, entries: string[]): void {
        for (const entry of entries) {
            // Static config supports: token, token:distinct_id (legacy), token:distinct_id:value
            if (entry.includes(':distinct_id:')) {
                const [token, , distinctId] = entry.split(':')
                this.staticRestrictionMap.addRestriction(restriction, token, {
                    type: 'distinct_id',
                    value: distinctId,
                })
            } else if (entry.includes(':')) {
                // Legacy format: token:distinct_id
                const [token, distinctId] = entry.split(':')
                this.staticRestrictionMap.addRestriction(restriction, token, {
                    type: 'distinct_id',
                    value: distinctId,
                })
            } else {
                this.staticRestrictionMap.addRestriction(restriction, entry, { type: 'all' })
            }
        }
    }

    private async buildRestrictionMap(): Promise<RestrictionMap> {
        const dynamicRestrictions = await this.fetchDynamicRestrictionsFromRedis()

        const map = new RestrictionMap()
        map.merge(this.staticRestrictionMap)

        for (const { restriction, token, identifier } of dynamicRestrictions) {
            map.addRestriction(restriction, token, identifier)
        }

        return map
    }

    private async fetchDynamicRestrictionsFromRedis(): Promise<ParsedRestriction[]> {
        const restrictions: ParsedRestriction[] = []

        try {
            const redisClient = await this.redisPool.acquire()
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
                        const json = parseJSON(redisResult[1] as string)
                        const parseResult = RedisRestrictionArraySchema.safeParse(json)

                        if (!parseResult.success) {
                            logger.warn(`Failed to parse Redis restriction config for ${restriction}`, {
                                error: parseResult.error,
                            })
                            return
                        }

                        for (const item of parseResult.data) {
                            if (!item.pipelines?.includes(this.pipeline)) {
                                continue
                            }

                            restrictions.push({ restriction, token: item.token, identifier: item.identifier })
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
                await this.redisPool.release(redisClient)
            }
        } catch (error) {
            logger.warn('Error acquiring Redis client from pool for token restrictions', { error })
        }

        return restrictions
    }
}
