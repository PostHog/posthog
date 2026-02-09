import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { RedisPool } from '../../types'
import { EventIngestionRestrictionManager } from './manager'
import { REDIS_KEY_PREFIX, RedisRestrictionType } from './redis-schema'
import { RestrictionType } from './rules'

const createMockRedisPool = (): RedisPool => {
    const redisClient = {
        pipeline: jest.fn(),
        quit: jest.fn().mockResolvedValue(undefined),
    }

    return {
        acquire: jest.fn().mockResolvedValue(redisClient),
        release: jest.fn().mockResolvedValue(undefined),
    } as unknown as RedisPool
}

// Helper to create v2 Redis format entries
function toRedisV2Format(
    entries: Array<{
        token: string
        pipeline?: string
        distinct_ids?: string[]
        session_ids?: string[]
        event_names?: string[]
        event_uuids?: string[]
    }>
): string {
    return JSON.stringify(
        entries.map((e) => ({
            version: 2,
            token: e.token,
            pipelines: [e.pipeline ?? 'analytics'],
            distinct_ids: e.distinct_ids ?? [],
            session_ids: e.session_ids ?? [],
            event_names: e.event_names ?? [],
            event_uuids: e.event_uuids ?? [],
        }))
    )
}

// Helper to create v0 Redis format (legacy, for backward compatibility tests)
function toRedisV0Format(
    entries: Array<{
        token: string
        pipeline?: string
        distinct_id?: string
        session_id?: string
        event_name?: string
        event_uuid?: string
    }>
): string {
    return JSON.stringify(
        entries.map((e) => {
            const entry: Record<string, unknown> = {
                token: e.token,
                pipelines: [e.pipeline ?? 'analytics'],
            }
            if (e.distinct_id) {
                entry.distinct_id = e.distinct_id
            }
            if (e.session_id) {
                entry.session_id = e.session_id
            }
            if (e.event_name) {
                entry.event_name = e.event_name
            }
            if (e.event_uuid) {
                entry.event_uuid = e.event_uuid
            }
            return entry
        })
    )
}

describe('EventIngestionRestrictionManager', () => {
    let hub: { redisPool: GenericPool<Redis> }
    let redisClient: Redis
    let pipelineMock: any
    let manager: EventIngestionRestrictionManager

    beforeEach(async () => {
        pipelineMock = {
            get: jest.fn().mockReturnThis(),
            exec: jest.fn().mockResolvedValue([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ]),
        }

        const redisPool = createMockRedisPool()
        redisClient = await redisPool.acquire()
        redisClient.pipeline = jest.fn().mockReturnValue(pipelineMock)

        hub = { redisPool }

        manager = new EventIngestionRestrictionManager(hub.redisPool, {
            staticDropEventTokens: [],
            staticSkipPersonTokens: [],
            staticForceOverflowTokens: [],
        })
        jest.clearAllMocks()
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('constructor', () => {
        it('initializes with default values if no options provided', () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool)
            expect(mgr).toBeDefined()
        })

        it('initializes with provided static config', () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['token1'],
                staticSkipPersonTokens: ['token2'],
                staticForceOverflowTokens: ['token3'],
            })
            expect(mgr).toBeDefined()
        })
    })

    describe('v2 format parsing (AND logic)', () => {
        it('parses v2 format with arrays', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [
                    null,
                    toRedisV2Format([
                        { token: 'token1', distinct_ids: ['user1', 'user2'], event_names: ['$pageview'] },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            // AND logic: both distinct_id AND event must match
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'user1', event: '$pageview' })).toContain(
                RestrictionType.DROP_EVENT
            )

            // Only distinct_id matches, event doesn't
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'user1', event: '$other' })).not.toContain(
                RestrictionType.DROP_EVENT
            )

            // Only event matches, distinct_id doesn't
            expect(
                manager.getAppliedRestrictions('token1', { distinct_id: 'other', event: '$pageview' })
            ).not.toContain(RestrictionType.DROP_EVENT)
        })

        it('parses v2 format with token-level restriction (all arrays empty)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            // Empty arrays = applies to all events for this token
            expect(manager.getAppliedRestrictions('token1')).toContain(RestrictionType.DROP_EVENT)
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'any', event: 'any' })).toContain(
                RestrictionType.DROP_EVENT
            )
        })

        it('handles v2 format with all filter types (AND logic)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [
                    null,
                    toRedisV2Format([
                        {
                            token: 'token1',
                            distinct_ids: ['user1'],
                            session_ids: ['session1'],
                            event_names: ['$pageview'],
                            event_uuids: ['uuid-123'],
                        },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            // All four must match
            expect(
                manager.getAppliedRestrictions('token1', {
                    distinct_id: 'user1',
                    session_id: 'session1',
                    event: '$pageview',
                    uuid: 'uuid-123',
                })
            ).toContain(RestrictionType.DROP_EVENT)

            // Three match, one fails
            expect(
                manager.getAppliedRestrictions('token1', {
                    distinct_id: 'user1',
                    session_id: 'session1',
                    event: '$pageview',
                    uuid: 'wrong-uuid',
                })
            ).not.toContain(RestrictionType.DROP_EVENT)
        })
    })

    describe('v0 format backward compatibility', () => {
        it('parses v0 format (single identifier per entry)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, toRedisV0Format([{ token: 'token1', distinct_id: 'user1' }])],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'user1' })).toContain(
                RestrictionType.DROP_EVENT
            )
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'user2' })).not.toContain(
                RestrictionType.DROP_EVENT
            )
        })

        it('handles v0 format without identifiers (token-level)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, toRedisV0Format([{ token: 'token1' }])],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('token1')).toContain(RestrictionType.DROP_EVENT)
        })
    })

    describe('pipeline filtering', () => {
        it('filters by analytics pipeline (default)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [
                    null,
                    JSON.stringify([
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            distinct_ids: [],
                            session_ids: [],
                            event_names: [],
                            event_uuids: [],
                        },
                        {
                            version: 2,
                            token: 'token2',
                            pipelines: ['session_recordings'],
                            distinct_ids: [],
                            session_ids: [],
                            event_names: [],
                            event_uuids: [],
                        },
                        {
                            version: 2,
                            token: 'token3',
                            pipelines: ['analytics', 'session_recordings'],
                            distinct_ids: [],
                            session_ids: [],
                            event_names: [],
                            event_uuids: [],
                        },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('token1')).toContain(RestrictionType.DROP_EVENT)
            expect(manager.getAppliedRestrictions('token2')).toEqual(new Set())
            expect(manager.getAppliedRestrictions('token3')).toContain(RestrictionType.DROP_EVENT)
        })

        it('filters by session_recordings pipeline', async () => {
            const sessionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                pipeline: 'session_recordings',
            })

            pipelineMock.exec.mockResolvedValueOnce([
                [
                    null,
                    JSON.stringify([
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            distinct_ids: [],
                            session_ids: [],
                            event_names: [],
                            event_uuids: [],
                        },
                        {
                            version: 2,
                            token: 'token2',
                            pipelines: ['session_recordings'],
                            distinct_ids: [],
                            session_ids: [],
                            event_names: [],
                            event_uuids: [],
                        },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            await sessionManager.forceRefresh()

            expect(sessionManager.getAppliedRestrictions('token1')).toEqual(new Set())
            expect(sessionManager.getAppliedRestrictions('token2')).toContain(RestrictionType.DROP_EVENT)
        })
    })

    describe('static config', () => {
        it('applies token-level static restriction', async () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['static-token'],
            })
            await mgr.forceRefresh()

            expect(mgr.getAppliedRestrictions('static-token')).toContain(RestrictionType.DROP_EVENT)
            expect(mgr.getAppliedRestrictions('other-token')).toEqual(new Set())
        })

        it('applies distinct_id static restriction (legacy format)', async () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['static-token:user1'],
            })
            await mgr.forceRefresh()

            expect(mgr.getAppliedRestrictions('static-token', { distinct_id: 'user1' })).toContain(
                RestrictionType.DROP_EVENT
            )
            expect(mgr.getAppliedRestrictions('static-token', { distinct_id: 'user2' })).toEqual(new Set())
        })

        it('applies distinct_id static restriction (explicit format)', async () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['static-token:distinct_id:user1'],
            })
            await mgr.forceRefresh()

            expect(mgr.getAppliedRestrictions('static-token', { distinct_id: 'user1' })).toContain(
                RestrictionType.DROP_EVENT
            )
        })

        it('combines static and dynamic restrictions', async () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['combo-token'],
            })

            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, toRedisV2Format([{ token: 'combo-token' }])],
                [null, null],
                [null, null],
            ])
            await mgr.forceRefresh()

            const restrictions = mgr.getAppliedRestrictions('combo-token')
            expect(restrictions).toContain(RestrictionType.DROP_EVENT)
            expect(restrictions).toContain(RestrictionType.SKIP_PERSON_PROCESSING)
        })
    })

    describe('all restriction types', () => {
        it('returns all four restriction types for matching token', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, toRedisV2Format([{ token: 'token1' }])],
            ])

            await manager.forceRefresh()

            const restrictions = manager.getAppliedRestrictions('token1')
            expect(restrictions).toContain(RestrictionType.DROP_EVENT)
            expect(restrictions).toContain(RestrictionType.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(RestrictionType.FORCE_OVERFLOW)
            expect(restrictions).toContain(RestrictionType.REDIRECT_TO_DLQ)
            expect(restrictions.size).toBe(4)
        })

        it('returns empty set when no token matches', async () => {
            await manager.forceRefresh()
            expect(manager.getAppliedRestrictions('unknown-token')).toEqual(new Set())
        })

        it('returns empty set when token is missing', () => {
            expect(manager.getAppliedRestrictions(undefined)).toEqual(new Set())
        })
    })

    describe('error handling', () => {
        it('handles Redis errors gracefully', async () => {
            pipelineMock.exec.mockRejectedValueOnce(new Error('Redis error'))

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('any-token')).toEqual(new Set())
            expect(hub.redisPool.release).toHaveBeenCalledWith(redisClient)
        })

        it('handles Redis pool acquisition errors gracefully', async () => {
            hub.redisPool.acquire = jest.fn().mockRejectedValueOnce(new Error('Pool error'))

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('any-token')).toEqual(new Set())
        })

        it('handles malformed JSON gracefully', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, 'not valid json'],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('any-token')).toEqual(new Set())
        })
    })

    describe('Redis key usage', () => {
        it('fetches from correct Redis keys', async () => {
            await manager.forceRefresh()

            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RedisRestrictionType.DROP_EVENT_FROM_INGESTION}`
            )
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RedisRestrictionType.SKIP_PERSON_PROCESSING}`
            )
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RedisRestrictionType.FORCE_OVERFLOW_FROM_INGESTION}`
            )
            expect(pipelineMock.get).toHaveBeenCalledWith(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.REDIRECT_TO_DLQ}`)
        })
    })
})
