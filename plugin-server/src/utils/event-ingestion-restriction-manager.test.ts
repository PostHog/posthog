import { Redis } from 'ioredis'

import {
    EventIngestionRestrictionManager,
    EventIngestionRestrictionManagerHub,
    REDIS_KEY_PREFIX,
    RedisRestrictionType,
    Restriction,
} from './event-ingestion-restriction-manager'

jest.mock('./db/redis', () => {
    const redisClient = {
        pipeline: jest.fn(),
        quit: jest.fn().mockResolvedValue(undefined),
    }

    const redisPool = {
        acquire: jest.fn().mockResolvedValue(redisClient),
        release: jest.fn().mockResolvedValue(undefined),
    }

    return {
        createRedisPool: jest.fn().mockReturnValue(redisPool),
    }
})

describe('EventIngestionRestrictionManager', () => {
    let hub: EventIngestionRestrictionManagerHub
    let redisClient: Redis
    let pipelineMock: any
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager

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

        const redisPool = require('./db/redis').createRedisPool()
        redisClient = await redisPool.acquire()
        redisClient.pipeline = jest.fn().mockReturnValue(pipelineMock)

        hub = {
            USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG: true,
            redisPool: require('./db/redis').createRedisPool(),
        }

        eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
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
            const manager = new EventIngestionRestrictionManager(hub)
            expect(manager).toBeDefined()
        })

        it('initializes with provided options', () => {
            const manager = new EventIngestionRestrictionManager(hub, {
                staticDropEventTokens: ['token1'],
                staticSkipPersonTokens: ['token2'],
                staticForceOverflowTokens: ['token3'],
            })
            expect(manager).toBeDefined()
        })
    })

    describe('fetchDynamicEventIngestionRestrictionConfig', () => {
        beforeEach(() => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = true
        })

        it('returns empty object if dynamic config is disabled', async () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false
            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()
            expect(result).toEqual({})
            expect(hub.redisPool.acquire).not.toHaveBeenCalled()
        })

        it('never calls Redis through dynamicConfigRefresher when USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG is false', () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false

            const manager = new EventIngestionRestrictionManager(hub)

            const fetchSpy = jest.spyOn(manager, 'fetchDynamicEventIngestionRestrictionConfig')

            manager.getAppliedRestrictions('test-token')

            expect(fetchSpy).not.toHaveBeenCalled()
            expect(hub.redisPool.acquire).not.toHaveBeenCalled()
        })

        it('fetches and parses Redis data correctly', async () => {
            expect(pipelineMock.get).toHaveBeenCalledTimes(4)
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1', pipelines: ['analytics'] },
                        { token: 'token2', pipelines: ['analytics'] },
                    ]),
                ],
                [
                    null,
                    JSON.stringify([
                        { token: 'token3', pipelines: ['analytics'] },
                        { token: 'token4', pipelines: ['analytics'] },
                    ]),
                ],
                [
                    null,
                    JSON.stringify([
                        { token: 'token5', pipelines: ['analytics'] },
                        { token: 'token6', pipelines: ['analytics'] },
                    ]),
                ],
                [
                    null,
                    JSON.stringify([
                        { token: 'token7', pipelines: ['analytics'] },
                        { token: 'token8', pipelines: ['analytics'] },
                    ]),
                ],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [Restriction.DROP_EVENT]: new Set(['token1', 'token2']),
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token3', 'token4']),
                [Restriction.FORCE_OVERFLOW]: new Set(['token5', 'token6']),
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token7', 'token8']),
            })

            expect(hub.redisPool.acquire).toHaveBeenCalled()
            expect(pipelineMock.get).toHaveBeenCalledTimes(4)
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
            expect(hub.redisPool.release).toHaveBeenCalledWith(redisClient)
        })

        it('handles Redis errors gracefully', async () => {
            const error = new Error('Redis error')
            pipelineMock.exec.mockRejectedValue(error)

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()
            expect(result).toEqual({})
            expect(hub.redisPool.release).toHaveBeenCalledWith(redisClient)
        })

        it('handles Redis pool acquisition errors gracefully', async () => {
            const error = new Error('Pool error')
            require('./db/redis').createRedisPool().acquire.mockRejectedValueOnce(error)

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()
            expect(result).toEqual({})
        })

        it('handles new format with pipeline fields (analytics pipeline)', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1', pipelines: ['analytics'] },
                        { token: 'token2', distinct_id: 'user1', pipelines: ['analytics', 'session_recordings'] },
                        { token: 'token3', pipelines: ['session_recordings'] },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [Restriction.DROP_EVENT]: new Set(['token1', 'token2:distinct_id:user1']),
            })
        })

        it('handles new format with only session_recordings enabled (analytics pipeline)', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [null, JSON.stringify([{ token: 'token1', pipelines: ['session_recordings'] }])],
                [null, null],
                [null, null],
                [null, null],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [Restriction.DROP_EVENT]: new Set([]),
            })
        })

        it('excludes entries with empty pipelines array', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1', pipelines: [] },
                        { token: 'token2', pipelines: ['analytics'] },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [Restriction.DROP_EVENT]: new Set(['token2']),
            })
        })

        it('ignores old format entries (analytics pipeline)', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [
                    null,
                    JSON.stringify([
                        'old-token1',
                        'old-token2:distinct1',
                        { token: 'new-token1', pipelines: ['analytics'] },
                        { token: 'new-token2', distinct_id: 'user1', pipelines: ['session_recordings'] },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [Restriction.DROP_EVENT]: new Set(['new-token1']),
            })
        })

        it('excludes entries when pipeline field is missing', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [null, JSON.stringify([{ token: 'token1' }, { token: 'token2', pipelines: ['analytics'] }])],
                [null, null],
                [null, null],
                [null, null],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [Restriction.DROP_EVENT]: new Set(['token2']),
            })
        })

        it('filters by session_recordings pipeline', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1', pipelines: ['analytics'] },
                        { token: 'token2', pipelines: ['session_recordings'] },
                        { token: 'token3', pipelines: ['analytics', 'session_recordings'] },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            const manager = new EventIngestionRestrictionManager(hub, {
                pipeline: 'session_recordings',
            })

            const result = await manager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [Restriction.DROP_EVENT]: new Set(['token2', 'token3']),
            })
        })

        it('old format excluded from session_recordings pipeline', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [null, JSON.stringify(['old-token1', { token: 'new-token1', pipelines: ['session_recordings'] }])],
                [null, null],
                [null, null],
                [null, null],
            ])

            const manager = new EventIngestionRestrictionManager(hub, {
                pipeline: 'session_recordings',
            })

            const result = await manager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [Restriction.DROP_EVENT]: new Set(['new-token1']),
            })
        })
    })

    describe('getAppliedRestrictions - DROP_EVENT', () => {
        it('returns empty array if token is not provided', () => {
            expect(eventIngestionRestrictionManager.getAppliedRestrictions()).toEqual([])
        })

        it('includes DROP_EVENT if token is in static drop list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticDropEventTokens: ['static-drop-token'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-drop-token')).toContain(
                Restriction.DROP_EVENT
            )
        })

        it('includes DROP_EVENT if token:distinctId is in static drop list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticDropEventTokens: ['static-drop-token:distinct_id:123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-drop-token', '123')).toContain(
                Restriction.DROP_EVENT
            )
        })

        it('returns empty array if dynamic config is disabled', () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual([])
        })

        it('returns empty array if dynamic set is not defined', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {}
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual([])
        })

        it('includes DROP_EVENT if token is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['token']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toContain(Restriction.DROP_EVENT)
        })

        it('includes DROP_EVENT if distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['token:distinct_id:123']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', '123')).toContain(
                Restriction.DROP_EVENT
            )
        })

        it('does not include DROP_EVENT if neither token nor distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['other-token', 'token:distinct_id:789']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', '123')).not.toContain(
                Restriction.DROP_EVENT
            )
        })
    })

    describe('getAppliedRestrictions - SKIP_PERSON_PROCESSING', () => {
        it('returns empty array if token is not provided', () => {
            expect(eventIngestionRestrictionManager.getAppliedRestrictions()).toEqual([])
        })

        it('includes SKIP_PERSON_PROCESSING if token is in static skip list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticSkipPersonTokens: ['static-skip-token'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-skip-token')).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
        })

        it('includes SKIP_PERSON_PROCESSING if token:distinctId is in static skip list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticSkipPersonTokens: ['static-skip-token:distinct_id:123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-skip-token', '123')).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
        })

        it('returns empty array if dynamic config is disabled', () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual([])
        })

        it('returns empty array if dynamic set is not defined', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {}
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual([])
        })

        it('includes SKIP_PERSON_PROCESSING if token is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
        })

        it('includes SKIP_PERSON_PROCESSING if distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token:distinct_id:123']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', '123')).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
        })

        it('does not include SKIP_PERSON_PROCESSING if neither token nor distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['other-token', 'token:distinct_id:789']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', '123')).not.toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
        })
    })

    describe('getAppliedRestrictions - FORCE_OVERFLOW', () => {
        it('returns empty array if token is not provided', () => {
            expect(eventIngestionRestrictionManager.getAppliedRestrictions()).toEqual([])
        })

        it('includes FORCE_OVERFLOW if token is in static overflow list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticForceOverflowTokens: ['static-overflow-token'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-overflow-token')).toContain(
                Restriction.FORCE_OVERFLOW
            )
        })

        it('includes FORCE_OVERFLOW if token:distinctId is in static overflow list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticForceOverflowTokens: ['static-overflow-token:distinct_id:123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-overflow-token', '123')).toContain(
                Restriction.FORCE_OVERFLOW
            )
        })

        it('returns empty array if dynamic config is disabled', () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual([])
        })

        it('returns empty array if dynamic set is not defined', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {}
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual([])
        })

        it('includes FORCE_OVERFLOW if token is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.FORCE_OVERFLOW]: new Set(['token']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toContain(
                Restriction.FORCE_OVERFLOW
            )
        })

        it('includes FORCE_OVERFLOW if distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.FORCE_OVERFLOW]: new Set(['token:distinct_id:123']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', '123')).toContain(
                Restriction.FORCE_OVERFLOW
            )
        })

        it('does not include FORCE_OVERFLOW if neither token nor distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.FORCE_OVERFLOW]: new Set(['other-token', 'token:distinct_id:789']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', '123')).not.toContain(
                Restriction.FORCE_OVERFLOW
            )
        })
    })

    describe('getAppliedRestrictions - REDIRECT_TO_DLQ', () => {
        it('returns empty array if token is not provided', () => {
            expect(eventIngestionRestrictionManager.getAppliedRestrictions()).toEqual([])
        })

        it('includes REDIRECT_TO_DLQ if token is in static DLQ list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticRedirectToDlqTokens: ['static-dlq-token'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-dlq-token')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('includes REDIRECT_TO_DLQ if token:distinctId is in static DLQ list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticRedirectToDlqTokens: ['static-dlq-token:distinct_id:123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-dlq-token', '123')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('returns empty array if dynamic config is disabled', () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual([])
        })

        it('returns empty array if dynamic set is not defined', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {}
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual([])
        })

        it('includes REDIRECT_TO_DLQ if token is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('includes REDIRECT_TO_DLQ if distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token:distinct_id:123']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', '123')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('does not include REDIRECT_TO_DLQ if neither token nor distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.REDIRECT_TO_DLQ]: new Set(['other-token', 'token:distinct_id:789']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', '123')).not.toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('includes REDIRECT_TO_DLQ if session_id is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token:session_id:session123']),
            }
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, 'session123')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('includes REDIRECT_TO_DLQ if event_name is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token:event_name:$pageview']),
            }
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, undefined, '$pageview')
            ).toContain(Restriction.REDIRECT_TO_DLQ)
        })

        it('includes REDIRECT_TO_DLQ if event_uuid is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token:event_uuid:uuid-123']),
            }
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions(
                    'token',
                    undefined,
                    undefined,
                    undefined,
                    'uuid-123'
                )
            ).toContain(Restriction.REDIRECT_TO_DLQ)
        })
    })

    describe('session_id support', () => {
        describe('fetchDynamicEventIngestionRestrictionConfig with session_ids', () => {
            it('handles new format with session_id field', async () => {
                pipelineMock.get.mockClear()
                pipelineMock.exec.mockResolvedValue([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', session_id: 'session123', pipelines: ['analytics'] },
                            { token: 'token2', distinct_id: 'user1', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

                expect(result).toEqual({
                    [Restriction.DROP_EVENT]: new Set(['token1:session_id:session123', 'token2:distinct_id:user1']),
                })
            })

            it('handles mixed distinct_id and session_id entries', async () => {
                pipelineMock.get.mockClear()
                pipelineMock.exec.mockResolvedValue([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', distinct_id: 'user1', pipelines: ['analytics'] },
                            { token: 'token1', session_id: 'session123', pipelines: ['analytics'] },
                            { token: 'token2', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

                expect(result).toEqual({
                    [Restriction.DROP_EVENT]: new Set([
                        'token1:distinct_id:user1',
                        'token1:session_id:session123',
                        'token2',
                    ]),
                })
            })
        })

        describe('getAppliedRestrictions with session_id - DROP_EVENT', () => {
            it('includes DROP_EVENT if session_id is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set(['token:session_id:session123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, 'session123')
                ).toContain(Restriction.DROP_EVENT)
            })

            it('includes DROP_EVENT if either distinct_id OR session_id matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set(['token:distinct_id:user1', 'token:session_id:session123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'user1', 'other-session')
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'other-user', 'session123')
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'other-user', 'other-session')
                ).not.toContain(Restriction.DROP_EVENT)
            })

            it('does not include DROP_EVENT if session_id does not match', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set(['token:session_id:session123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, 'other-session')
                ).not.toContain(Restriction.DROP_EVENT)
            })
        })

        describe('getAppliedRestrictions with session_id - SKIP_PERSON_PROCESSING', () => {
            it('includes SKIP_PERSON_PROCESSING if session_id is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token:session_id:session123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, 'session123')
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
            })

            it('includes SKIP_PERSON_PROCESSING if either distinct_id OR session_id matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.SKIP_PERSON_PROCESSING]: new Set([
                        'token:distinct_id:user1',
                        'token:session_id:session123',
                    ]),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'user1', 'other-session')
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'other-user', 'session123')
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'other-user', 'other-session')
                ).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            })
        })

        describe('getAppliedRestrictions with session_id - FORCE_OVERFLOW', () => {
            it('includes FORCE_OVERFLOW if session_id is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.FORCE_OVERFLOW]: new Set(['token:session_id:session123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, 'session123')
                ).toContain(Restriction.FORCE_OVERFLOW)
            })

            it('includes FORCE_OVERFLOW if either distinct_id OR session_id matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.FORCE_OVERFLOW]: new Set(['token:distinct_id:user1', 'token:session_id:session123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'user1', 'other-session')
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'other-user', 'session123')
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', 'other-user', 'other-session')
                ).not.toContain(Restriction.FORCE_OVERFLOW)
            })
        })
    })

    describe('event_name support', () => {
        describe('fetchDynamicEventIngestionRestrictionConfig with event_name', () => {
            it('handles new format with event_name field', async () => {
                pipelineMock.get.mockClear()
                pipelineMock.exec.mockResolvedValue([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', event_name: '$pageview', pipelines: ['analytics'] },
                            { token: 'token2', distinct_id: 'user1', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

                expect(result).toEqual({
                    [Restriction.DROP_EVENT]: new Set(['token1:event_name:$pageview', 'token2:distinct_id:user1']),
                })
            })

            it('handles mixed distinct_id, session_id, and event_name entries', async () => {
                pipelineMock.get.mockClear()
                pipelineMock.exec.mockResolvedValue([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', distinct_id: 'user1', pipelines: ['analytics'] },
                            { token: 'token1', session_id: 'session123', pipelines: ['analytics'] },
                            { token: 'token1', event_name: '$pageview', pipelines: ['analytics'] },
                            { token: 'token2', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

                expect(result).toEqual({
                    [Restriction.DROP_EVENT]: new Set([
                        'token1:distinct_id:user1',
                        'token1:session_id:session123',
                        'token1:event_name:$pageview',
                        'token2',
                    ]),
                })
            })
        })

        describe('getAppliedRestrictions with event_name - DROP_EVENT', () => {
            it('includes DROP_EVENT if event_name is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set(['token:event_name:$pageview']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, undefined, '$pageview')
                ).toContain(Restriction.DROP_EVENT)
            })

            it('includes DROP_EVENT if any filter matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set([
                        'token:distinct_id:user1',
                        'token:session_id:session123',
                        'token:event_name:$pageview',
                    ]),
                }
                // Match by distinct_id
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'user1',
                        'other-session',
                        'other-event'
                    )
                ).toContain(Restriction.DROP_EVENT)
                // Match by session_id
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'session123',
                        'other-event'
                    )
                ).toContain(Restriction.DROP_EVENT)
                // Match by event_name
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        '$pageview'
                    )
                ).toContain(Restriction.DROP_EVENT)
                // No match
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        'other-event'
                    )
                ).not.toContain(Restriction.DROP_EVENT)
            })

            it('does not include DROP_EVENT if event_name does not match', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set(['token:event_name:$pageview']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        undefined,
                        undefined,
                        '$autocapture'
                    )
                ).not.toContain(Restriction.DROP_EVENT)
            })
        })

        describe('getAppliedRestrictions with event_name - SKIP_PERSON_PROCESSING', () => {
            it('includes SKIP_PERSON_PROCESSING if event_name is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token:event_name:$pageview']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, undefined, '$pageview')
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
            })

            it('includes SKIP_PERSON_PROCESSING if any filter matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.SKIP_PERSON_PROCESSING]: new Set([
                        'token:distinct_id:user1',
                        'token:event_name:$pageview',
                    ]),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'user1',
                        'other-session',
                        'other-event'
                    )
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        '$pageview'
                    )
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        'other-event'
                    )
                ).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            })
        })

        describe('getAppliedRestrictions with event_name - FORCE_OVERFLOW', () => {
            it('includes FORCE_OVERFLOW if event_name is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.FORCE_OVERFLOW]: new Set(['token:event_name:$pageview']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', undefined, undefined, '$pageview')
                ).toContain(Restriction.FORCE_OVERFLOW)
            })

            it('includes FORCE_OVERFLOW if any filter matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.FORCE_OVERFLOW]: new Set(['token:distinct_id:user1', 'token:event_name:$pageview']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'user1',
                        'other-session',
                        'other-event'
                    )
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        '$pageview'
                    )
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        'other-event'
                    )
                ).not.toContain(Restriction.FORCE_OVERFLOW)
            })
        })
    })

    describe('event_uuid support', () => {
        describe('fetchDynamicEventIngestionRestrictionConfig with event_uuid', () => {
            it('handles new format with event_uuid field', async () => {
                pipelineMock.get.mockClear()
                pipelineMock.exec.mockResolvedValue([
                    [
                        null,
                        JSON.stringify([
                            {
                                token: 'token1',
                                event_uuid: '550e8400-e29b-41d4-a716-446655440000',
                                pipelines: ['analytics'],
                            },
                            { token: 'token2', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

                expect(result).toEqual({
                    [Restriction.DROP_EVENT]: new Set([
                        'token1:event_uuid:550e8400-e29b-41d4-a716-446655440000',
                        'token2',
                    ]),
                })
            })

            it('handles mixed distinct_id, session_id, and event_uuid entries', async () => {
                pipelineMock.get.mockClear()
                pipelineMock.exec.mockResolvedValue([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', distinct_id: 'user1', pipelines: ['analytics'] },
                            { token: 'token1', session_id: 'session123', pipelines: ['analytics'] },
                            { token: 'token1', event_uuid: 'uuid-123', pipelines: ['analytics'] },
                            { token: 'token2', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

                expect(result).toEqual({
                    [Restriction.DROP_EVENT]: new Set([
                        'token1:distinct_id:user1',
                        'token1:session_id:session123',
                        'token1:event_uuid:uuid-123',
                        'token2',
                    ]),
                })
            })
        })

        describe('getAppliedRestrictions with event_uuid - DROP_EVENT', () => {
            it('includes DROP_EVENT if event_uuid is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set(['token:event_uuid:uuid-123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        undefined,
                        undefined,
                        undefined,
                        'uuid-123'
                    )
                ).toContain(Restriction.DROP_EVENT)
            })

            it('includes DROP_EVENT if any filter matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set([
                        'token:distinct_id:user1',
                        'token:session_id:session123',
                        'token:event_uuid:uuid-123',
                    ]),
                }
                // Match by distinct_id
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'user1',
                        'other-session',
                        undefined,
                        'other-uuid'
                    )
                ).toContain(Restriction.DROP_EVENT)
                // Match by session_id
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'session123',
                        undefined,
                        'other-uuid'
                    )
                ).toContain(Restriction.DROP_EVENT)
                // Match by event_uuid
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        undefined,
                        'uuid-123'
                    )
                ).toContain(Restriction.DROP_EVENT)
                // No match
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        undefined,
                        'other-uuid'
                    )
                ).not.toContain(Restriction.DROP_EVENT)
            })

            it('does not include DROP_EVENT if event_uuid does not match', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.DROP_EVENT]: new Set(['token:event_uuid:uuid-123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        undefined,
                        undefined,
                        undefined,
                        'other-uuid'
                    )
                ).not.toContain(Restriction.DROP_EVENT)
            })
        })

        describe('getAppliedRestrictions with event_uuid - SKIP_PERSON_PROCESSING', () => {
            it('includes SKIP_PERSON_PROCESSING if event_uuid is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token:event_uuid:uuid-123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        undefined,
                        undefined,
                        undefined,
                        'uuid-123'
                    )
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
            })

            it('includes SKIP_PERSON_PROCESSING if any filter matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.SKIP_PERSON_PROCESSING]: new Set([
                        'token:distinct_id:user1',
                        'token:event_uuid:uuid-123',
                    ]),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'user1',
                        'other-session',
                        undefined,
                        'other-uuid'
                    )
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        undefined,
                        'uuid-123'
                    )
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        undefined,
                        'other-uuid'
                    )
                ).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            })
        })

        describe('getAppliedRestrictions with event_uuid - FORCE_OVERFLOW', () => {
            it('includes FORCE_OVERFLOW if event_uuid is in the dynamic config list', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.FORCE_OVERFLOW]: new Set(['token:event_uuid:uuid-123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        undefined,
                        undefined,
                        undefined,
                        'uuid-123'
                    )
                ).toContain(Restriction.FORCE_OVERFLOW)
            })

            it('includes FORCE_OVERFLOW if any filter matches (OR logic)', () => {
                // @ts-expect-error - Setting private property for testing
                eventIngestionRestrictionManager.latestDynamicConfig = {
                    [Restriction.FORCE_OVERFLOW]: new Set(['token:distinct_id:user1', 'token:event_uuid:uuid-123']),
                }
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'user1',
                        'other-session',
                        undefined,
                        'other-uuid'
                    )
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        undefined,
                        'uuid-123'
                    )
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions(
                        'token',
                        'other-user',
                        'other-session',
                        undefined,
                        'other-uuid'
                    )
                ).not.toContain(Restriction.FORCE_OVERFLOW)
            })
        })
    })

    describe('multiple restrictions for same entity', () => {
        it('returns multiple restrictions when token matches multiple static lists', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticDropEventTokens: ['multi-token'],
                staticSkipPersonTokens: ['multi-token'],
                staticForceOverflowTokens: ['multi-token'],
                staticRedirectToDlqTokens: ['multi-token'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('multi-token')
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions).toHaveLength(4)
        })

        it('returns multiple restrictions when token matches multiple dynamic config lists', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['token']),
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token']),
                [Restriction.FORCE_OVERFLOW]: new Set(['token']),
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token']),
            }
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token')
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions).toHaveLength(4)
        })

        it('returns DROP_EVENT and SKIP_PERSON_PROCESSING for token:distinct_id combination', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['token:distinct_id:user1']),
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token:distinct_id:user1']),
            }
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token', 'user1')
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).not.toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).not.toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions).toHaveLength(2)
        })

        it('returns FORCE_OVERFLOW and REDIRECT_TO_DLQ for session_id', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.FORCE_OVERFLOW]: new Set(['token:session_id:session123']),
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token:session_id:session123']),
            }
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions(
                'token',
                undefined,
                'session123'
            )
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions).not.toContain(Restriction.DROP_EVENT)
            expect(restrictions).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toHaveLength(2)
        })

        it('combines static and dynamic restrictions', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
                staticDropEventTokens: ['combo-token'],
                staticSkipPersonTokens: [],
                staticForceOverflowTokens: [],
                staticRedirectToDlqTokens: [],
            })
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['combo-token']),
                [Restriction.FORCE_OVERFLOW]: new Set(['combo-token']),
            }
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('combo-token')
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).not.toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions).toHaveLength(3)
        })

        it('matches different restriction types by different identifiers', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['token:distinct_id:user1']),
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token:session_id:session123']),
                [Restriction.FORCE_OVERFLOW]: new Set(['token:event_name:$pageview']),
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token:event_uuid:uuid-abc']),
            }
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions(
                'token',
                'user1',
                'session123',
                '$pageview',
                'uuid-abc'
            )
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions).toHaveLength(4)
        })

        it('returns partial matches when only some identifiers match', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['token:distinct_id:user1']),
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token:session_id:other-session']),
                [Restriction.FORCE_OVERFLOW]: new Set(['token:event_name:$pageview']),
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token:event_uuid:other-uuid']),
            }
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions(
                'token',
                'user1',
                'session123',
                '$pageview',
                'uuid-abc'
            )
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).not.toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions).toHaveLength(2)
        })

        it('returns empty when no restrictions match despite having configs', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['other-token']),
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token:distinct_id:other-user']),
                [Restriction.FORCE_OVERFLOW]: new Set(['token:session_id:other-session']),
                [Restriction.REDIRECT_TO_DLQ]: new Set(['token:event_name:other-event']),
            }
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions(
                'token',
                'user1',
                'session123',
                '$pageview'
            )
            expect(restrictions).toHaveLength(0)
        })

        it('token-level restriction applies regardless of other identifiers', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [Restriction.DROP_EVENT]: new Set(['token']),
                [Restriction.SKIP_PERSON_PROCESSING]: new Set(['token']),
            }
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions(
                'token',
                'any-user',
                'any-session',
                'any-event',
                'any-uuid'
            )
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toHaveLength(2)
        })
    })
})
