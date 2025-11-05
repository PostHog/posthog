import { Redis } from 'ioredis'

import { Hub } from '../types'
import {
    EventIngestionRestrictionManager,
    REDIS_KEY_PREFIX,
    RestrictionType,
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
    let hub: Hub
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
            ]),
        }

        const redisPool = require('./db/redis').createRedisPool()
        redisClient = await redisPool.acquire()
        redisClient.pipeline = jest.fn().mockReturnValue(pipelineMock)

        hub = {
            USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG: true,
            redisPool: require('./db/redis').createRedisPool(),
        } as unknown as Hub

        eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub as Hub, {
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
            const manager = new EventIngestionRestrictionManager(hub as Hub)
            expect(manager).toBeDefined()
        })

        it('initializes with provided options', () => {
            const manager = new EventIngestionRestrictionManager(hub as Hub, {
                staticDropEventTokens: ['token1'],
                staticSkipPersonTokens: ['token2'],
                staticForceOverflowTokens: ['token3'],
            })
            expect(manager).toBeDefined()
        })
    })

    describe('fetchDynamicEventIngestionRestrictionConfig', () => {
        beforeEach(() => {
            // Set the property to enable dynamic config
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

            // Create a new manager with the flag set to false
            const manager = new EventIngestionRestrictionManager(hub as Hub)

            // Create a spy on the fetchDynamicEventIngestionRestrictionConfig method
            const fetchSpy = jest.spyOn(manager, 'fetchDynamicEventIngestionRestrictionConfig')

            // Call the methods that might trigger Redis access
            manager.shouldDropEvent('test-token')
            manager.shouldSkipPerson('test-token')
            manager.shouldForceOverflow('test-token')

            // Verify that fetchDynamicEventIngestionRestrictionConfig was never called
            expect(fetchSpy).not.toHaveBeenCalled()

            // Additionally verify Redis wasn't accessed
            expect(hub.redisPool.acquire).not.toHaveBeenCalled()
        })

        it('fetches and parses Redis data correctly', async () => {
            // on class initialization, we load the cache, so assert that pipeline get was called 3 times
            expect(pipelineMock.get).toHaveBeenCalledTimes(3)
            // now clear the mock, so we can assert again below
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [null, JSON.stringify(['token1', 'token2'])],
                [null, JSON.stringify(['token3', 'token4'])],
                [null, JSON.stringify(['token5', 'token6'])],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['token1', 'token2']),
                [RestrictionType.SKIP_PERSON_PROCESSING]: new Set(['token3', 'token4']),
                [RestrictionType.FORCE_OVERFLOW_FROM_INGESTION]: new Set(['token5', 'token6']),
            })

            expect(hub.redisPool.acquire).toHaveBeenCalled()
            expect(pipelineMock.get).toHaveBeenCalledTimes(3)
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RestrictionType.DROP_EVENT_FROM_INGESTION}`
            )
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RestrictionType.SKIP_PERSON_PROCESSING}`
            )
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RestrictionType.FORCE_OVERFLOW_FROM_INGESTION}`
            )
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
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            // Should only include token1 and token2 (pipelines includes 'analytics'), not token3
            expect(result).toEqual({
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['token1', 'token2:user1']),
            })
        })

        it('handles new format with only session_recordings enabled (analytics pipeline)', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [null, JSON.stringify([{ token: 'token1', pipelines: ['session_recordings'] }])],
                [null, null],
                [null, null],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            // Should be empty because pipelines doesn't include 'analytics'
            expect(result).toEqual({
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set([]),
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
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            expect(result).toEqual({
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['token2']),
            })
        })

        it('handles mixed old and new formats (analytics pipeline)', async () => {
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
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            // Should include old-token1, old-token2:distinct1 (old format defaults to analytics)
            // and new-token1 (pipelines includes 'analytics'), but NOT new-token2
            expect(result).toEqual({
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set([
                    'old-token1',
                    'old-token2:distinct1',
                    'new-token1',
                ]),
            })
        })

        it('excludes entries when pipeline field is missing', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1' }, // Missing pipelines field - will be excluded
                        { token: 'token2', pipelines: ['analytics'] }, // Has pipelines field
                    ]),
                ],
                [null, null],
                [null, null],
            ])

            const result = await eventIngestionRestrictionManager.fetchDynamicEventIngestionRestrictionConfig()

            // Should only include token2 (pipelines includes 'analytics'), token1 is excluded (missing field)
            expect(result).toEqual({
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['token2']),
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
            ])

            const manager = new EventIngestionRestrictionManager(hub as Hub, {
                pipeline: 'session_recordings',
            })

            const result = await manager.fetchDynamicEventIngestionRestrictionConfig()

            // Should only include token2 and token3 (pipelines includes 'session_recordings')
            expect(result).toEqual({
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['token2', 'token3']),
            })
        })

        it('old format excluded from session_recordings pipeline', async () => {
            pipelineMock.get.mockClear()
            pipelineMock.exec.mockResolvedValue([
                [
                    null,
                    JSON.stringify([
                        'old-token1', // Old format, should be excluded from session_recordings
                        { token: 'new-token1', pipelines: ['session_recordings'] },
                    ]),
                ],
                [null, null],
                [null, null],
            ])

            const manager = new EventIngestionRestrictionManager(hub as Hub, {
                pipeline: 'session_recordings',
            })

            const result = await manager.fetchDynamicEventIngestionRestrictionConfig()

            // Should only include new-token1, not old-token1 (old format defaults to analytics only)
            expect(result).toEqual({
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['new-token1']),
            })
        })
    })

    describe('shouldDropEvent', () => {
        it('returns false if token is not provided', () => {
            expect(eventIngestionRestrictionManager.shouldDropEvent()).toBe(false)
        })

        it('returns true if token is in static drop list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub as Hub, {
                staticDropEventTokens: ['static-drop-token'],
            })
            expect(eventIngestionRestrictionManager.shouldDropEvent('static-drop-token')).toBe(true)
        })

        it('returns true if token:distinctId is in static drop list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub as Hub, {
                staticDropEventTokens: ['static-drop-token:123'],
            })
            expect(eventIngestionRestrictionManager.shouldDropEvent('static-drop-token', '123')).toBe(true)
        })

        it('returns false if dynamic config is disabled', () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false
            expect(eventIngestionRestrictionManager.shouldDropEvent('token')).toBe(false)
        })

        it('returns false if dynamic set is not defined', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {}
            expect(eventIngestionRestrictionManager.shouldDropEvent('token')).toBe(false)
        })

        it('returns true if token is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['token']),
            }
            expect(eventIngestionRestrictionManager.shouldDropEvent('token')).toBe(true)
        })

        it('returns true if distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['token:123']),
            }
            expect(eventIngestionRestrictionManager.shouldDropEvent('token', '123')).toBe(true)
        })

        it('returns false if neither token nor distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.DROP_EVENT_FROM_INGESTION]: new Set(['other-token', 'token:789']),
            }
            expect(eventIngestionRestrictionManager.shouldDropEvent('token', '123')).toBe(false)
        })
    })

    describe('shouldSkipPerson', () => {
        it('returns false if token is not provided', () => {
            expect(eventIngestionRestrictionManager.shouldSkipPerson()).toBe(false)
        })

        it('returns true if token is in static skip list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub as Hub, {
                staticSkipPersonTokens: ['static-skip-token'],
            })
            expect(eventIngestionRestrictionManager.shouldSkipPerson('static-skip-token')).toBe(true)
        })

        it('returns true if token:distinctId is in static skip list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub as Hub, {
                staticSkipPersonTokens: ['static-skip-token:123'],
            })
            expect(eventIngestionRestrictionManager.shouldSkipPerson('static-skip-token', '123')).toBe(true)
        })

        it('returns false if dynamic config is disabled', () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false
            expect(eventIngestionRestrictionManager.shouldSkipPerson('token')).toBe(false)
        })

        it('returns false if dynamic set is not defined', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {}
            expect(eventIngestionRestrictionManager.shouldSkipPerson('token')).toBe(false)
        })

        it('returns true if token is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.SKIP_PERSON_PROCESSING]: new Set(['token']),
            }
            expect(eventIngestionRestrictionManager.shouldSkipPerson('token')).toBe(true)
        })

        it('returns true if distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.SKIP_PERSON_PROCESSING]: new Set(['token:123']),
            }
            expect(eventIngestionRestrictionManager.shouldSkipPerson('token', '123')).toBe(true)
        })

        it('returns false if neither token nor distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.SKIP_PERSON_PROCESSING]: new Set(['other-token', 'token:789']),
            }
            expect(eventIngestionRestrictionManager.shouldSkipPerson('token', '123')).toBe(false)
        })
    })

    describe('shouldForceOverflow', () => {
        it('returns false if token is not provided', () => {
            expect(eventIngestionRestrictionManager.shouldForceOverflow()).toBe(false)
        })

        it('returns true if token is in static overflow list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub as Hub, {
                staticForceOverflowTokens: ['static-overflow-token'],
            })
            expect(eventIngestionRestrictionManager.shouldForceOverflow('static-overflow-token')).toBe(true)
        })

        it('returns true if token:distinctId is in static overflow list', () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub as Hub, {
                staticForceOverflowTokens: ['static-overflow-token:123'],
            })
            expect(eventIngestionRestrictionManager.shouldForceOverflow('static-overflow-token', '123')).toBe(true)
        })

        it('returns false if dynamic config is disabled', () => {
            hub.USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG = false
            expect(eventIngestionRestrictionManager.shouldForceOverflow('token')).toBe(false)
        })

        it('returns false if dynamic set is not defined', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {}
            expect(eventIngestionRestrictionManager.shouldForceOverflow('token')).toBe(false)
        })

        it('returns true if token is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.FORCE_OVERFLOW_FROM_INGESTION]: new Set(['token']),
            }
            expect(eventIngestionRestrictionManager.shouldForceOverflow('token')).toBe(true)
        })

        it('returns true if distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.FORCE_OVERFLOW_FROM_INGESTION]: new Set(['token:123']),
            }
            expect(eventIngestionRestrictionManager.shouldForceOverflow('token', '123')).toBe(true)
        })

        it('returns false if neither token nor distinctId is in the dynamic config list', () => {
            // @ts-expect-error - Setting private property for testing
            eventIngestionRestrictionManager.latestDynamicConfig = {
                [RestrictionType.FORCE_OVERFLOW_FROM_INGESTION]: new Set(['other-token', 'token:789']),
            }
            expect(eventIngestionRestrictionManager.shouldForceOverflow('token', '123')).toBe(false)
        })
    })
})
