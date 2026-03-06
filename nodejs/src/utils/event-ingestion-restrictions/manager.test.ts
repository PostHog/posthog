import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { RedisPool } from '../../types'
import { logger } from '../logger'
import { EventIngestionRestrictionManager } from './manager'
import { REDIS_KEY_PREFIX, RedisRestrictionType } from './redis-schema'

jest.mock('../logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

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
                [null, null],
            ])

            await manager.forceRefresh()

            // AND logic: both distinct_id AND event must match
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'user1', event: '$pageview' }).drop).toBe(
                true
            )

            // Only distinct_id matches, event doesn't
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'user1', event: '$other' }).drop).toBe(null)

            // Only event matches, distinct_id doesn't
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'other', event: '$pageview' }).drop).toBe(
                null
            )
        })

        it('parses v2 format with token-level restriction (all arrays empty)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            // Empty arrays = applies to all events for this token
            expect(manager.getAppliedRestrictions('token1').drop).toBe(true)
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'any', event: 'any' }).drop).toBe(true)
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
                }).drop
            ).toBe(true)

            // Three match, one fails
            expect(
                manager.getAppliedRestrictions('token1', {
                    distinct_id: 'user1',
                    session_id: 'session1',
                    event: '$pageview',
                    uuid: 'wrong-uuid',
                }).drop
            ).toBe(null)
        })
    })

    describe('v0 format backward compatibility', () => {
        it('parses v0 format (single identifier per entry)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, toRedisV0Format([{ token: 'token1', distinct_id: 'user1' }])],
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'user1' }).drop).toBe(true)
            expect(manager.getAppliedRestrictions('token1', { distinct_id: 'user2' }).drop).toBe(null)
        })

        it('handles v0 format without identifiers (token-level)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, toRedisV0Format([{ token: 'token1' }])],
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('token1').drop).toBe(true)
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
                [null, null],
            ])

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('token1').drop).toBe(true)
            expect(manager.getAppliedRestrictions('token2').isEmpty).toBe(true)
            expect(manager.getAppliedRestrictions('token3').drop).toBe(true)
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
                [null, null],
            ])

            await sessionManager.forceRefresh()

            expect(sessionManager.getAppliedRestrictions('token1').isEmpty).toBe(true)
            expect(sessionManager.getAppliedRestrictions('token2').drop).toBe(true)
        })
    })

    describe('static config', () => {
        it('applies token-level static restriction', async () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['static-token'],
            })
            await mgr.forceRefresh()

            expect(mgr.getAppliedRestrictions('static-token').drop).toBe(true)
            expect(mgr.getAppliedRestrictions('other-token').isEmpty).toBe(true)
        })

        it('applies distinct_id static restriction (legacy format)', async () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['static-token:user1'],
            })
            await mgr.forceRefresh()

            expect(mgr.getAppliedRestrictions('static-token', { distinct_id: 'user1' }).drop).toBe(true)
            expect(mgr.getAppliedRestrictions('static-token', { distinct_id: 'user2' }).isEmpty).toBe(true)
        })

        it('applies distinct_id static restriction (explicit format)', async () => {
            const mgr = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['static-token:distinct_id:user1'],
            })
            await mgr.forceRefresh()

            expect(mgr.getAppliedRestrictions('static-token', { distinct_id: 'user1' }).drop).toBe(true)
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
                [null, null],
            ])
            await mgr.forceRefresh()

            const restrictions = mgr.getAppliedRestrictions('combo-token')
            expect(restrictions.drop).toBe(true)
            expect(restrictions.skipPersonProcessing).toBe(true)
        })
    })

    describe('all restriction types', () => {
        it('returns all non-redirect restriction types for matching token', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, toRedisV2Format([{ token: 'token1' }])],
                [null, null],
            ])

            await manager.forceRefresh()

            const restrictions = manager.getAppliedRestrictions('token1')
            expect(restrictions.drop).toBe(true)
            expect(restrictions.skipPersonProcessing).toBe(true)
            expect(restrictions.forceOverflow).toBe(true)
            expect(restrictions.redirectToDlq).toBe(true)
            expect(restrictions.isEmpty).toBe(false)
        })

        it('returns empty restrictions when no token matches', async () => {
            await manager.forceRefresh()
            const restrictions = manager.getAppliedRestrictions('unknown-token')
            expect(restrictions.isEmpty).toBe(true)
        })

        it('returns empty restrictions when token is missing', () => {
            const restrictions = manager.getAppliedRestrictions(undefined)
            expect(restrictions.isEmpty).toBe(true)
        })
    })

    describe('error handling', () => {
        it('handles Redis errors gracefully', async () => {
            pipelineMock.exec.mockRejectedValueOnce(new Error('Redis error'))

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('any-token').isEmpty).toBe(true)
            expect(hub.redisPool.release).toHaveBeenCalledWith(redisClient)
        })

        it('handles Redis pool acquisition errors gracefully', async () => {
            hub.redisPool.acquire = jest.fn().mockRejectedValueOnce(new Error('Pool error'))

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('any-token').isEmpty).toBe(true)
        })

        it('handles malformed JSON gracefully', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, 'not valid json'],
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ])

            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('any-token').isEmpty).toBe(true)
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
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RedisRestrictionType.REDIRECT_TO_TOPIC}`
            )
        })
    })

    describe('redirect_to_topic', () => {
        it('loads redirect_to_topic with valid args.topic', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
                [
                    null,
                    JSON.stringify([
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            args: { topic: 'custom-topic' },
                        },
                    ]),
                ],
            ])

            await manager.forceRefresh()

            const restrictions = manager.getAppliedRestrictions('token1')
            expect(restrictions.redirectToTopic).toBe('custom-topic')
        })

        it('skips redirect_to_topic entries with missing args.topic and logs error', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
                [
                    null,
                    JSON.stringify([
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                        },
                    ]),
                ],
            ])

            await manager.forceRefresh()

            const restrictions = manager.getAppliedRestrictions('token1')
            expect(restrictions.redirectToTopic).toBeNull()
            expect(restrictions.isEmpty).toBe(true)
            expect(logger.error).toHaveBeenCalledWith(
                'redirect_to_topic restriction missing valid args.topic, skipping',
                { token: 'token1' }
            )
        })

        it('skips redirect_to_topic entries with empty string topic', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
                [
                    null,
                    JSON.stringify([
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            args: { topic: '' },
                        },
                    ]),
                ],
            ])

            await manager.forceRefresh()

            const restrictions = manager.getAppliedRestrictions('token1')
            expect(restrictions.redirectToTopic).toBeNull()
            expect(logger.error).toHaveBeenCalled()
        })

        it('skips redirect_to_topic entries with null args', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
                [
                    null,
                    JSON.stringify([
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            args: null,
                        },
                    ]),
                ],
            ])

            await manager.forceRefresh()

            const restrictions = manager.getAppliedRestrictions('token1')
            expect(restrictions.redirectToTopic).toBeNull()
            expect(logger.error).toHaveBeenCalled()
        })

        it('last matching redirect_to_topic wins when sorted by index', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
                [
                    null,
                    JSON.stringify([
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            index: 2,
                            args: { topic: 'topic-b' },
                        },
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            index: 1,
                            args: { topic: 'topic-a' },
                        },
                    ]),
                ],
            ])

            await manager.forceRefresh()

            const restrictions = manager.getAppliedRestrictions('token1')
            expect(restrictions.redirectToTopic).toBe('topic-b')
        })

        it('sorts entries by index ascending', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
                [
                    null,
                    JSON.stringify([
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            index: 10,
                            args: { topic: 'topic-last' },
                        },
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            index: 5,
                            args: { topic: 'topic-middle' },
                        },
                        {
                            version: 2,
                            token: 'token1',
                            pipelines: ['analytics'],
                            index: 1,
                            args: { topic: 'topic-first' },
                        },
                    ]),
                ],
            ])

            await manager.forceRefresh()

            const restrictions = manager.getAppliedRestrictions('token1')
            expect(restrictions.redirectToTopic).toBe('topic-last')
        })
    })
})
