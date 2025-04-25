import { Redis } from 'ioredis'

import { Hub } from '../types'
import { RestrictionType, TokenRestrictionManager } from './token-restriction-manager'

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

describe('TokenRestrictionManager', () => {
    let hub: Hub
    let redisClient: Redis
    let pipelineMock: any
    let tokenRestrictionManager: TokenRestrictionManager

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
            USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG: true,
            redisPool: require('./db/redis').createRedisPool(),
        } as unknown as Hub

        tokenRestrictionManager = new TokenRestrictionManager(hub as Hub, {
            cacheSize: 1000,
            ttlMs: 1000 * 60 * 60 * 24,
            dropEventTokens: [],
            skipPersonTokens: [],
            forceOverflowTokens: [],
        })
        jest.clearAllMocks()
    })

    afterEach(() => {
        jest.clearAllMocks()
        tokenRestrictionManager.clear()
    })

    describe('constructor', () => {
        it('initializes with default values if no options provided', () => {
            const manager = new TokenRestrictionManager(hub as Hub)
            expect(manager).toBeDefined()
        })

        it('initializes with provided options', () => {
            const manager = new TokenRestrictionManager(hub as Hub, {
                cacheSize: 5,
                ttlMs: 5000,
                dropEventTokens: ['token1'],
                skipPersonTokens: ['token2'],
                forceOverflowTokens: ['token3'],
            })
            expect(manager).toBeDefined()
        })
    })

    describe('primeRestrictionsCache', () => {
        it('does nothing if token is not provided', async () => {
            await tokenRestrictionManager.primeRestrictionsCache('')
            expect(hub.redisPool.acquire).not.toHaveBeenCalled()
        })

        it('does nothing if Redis event filtering is disabled', async () => {
            hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG = false
            await tokenRestrictionManager.primeRestrictionsCache('token')
            expect(hub.redisPool.acquire).not.toHaveBeenCalled()
        })

        it('does nothing if all cache values are already present', async () => {
            const dropEventSpy = jest.spyOn(tokenRestrictionManager['dropEventCache'], 'get')
            const skipPersonSpy = jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'get')
            const forceOverflowSpy = jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'get')

            dropEventSpy.mockReturnValue('value')
            skipPersonSpy.mockReturnValue('value')
            forceOverflowSpy.mockReturnValue('value')

            await tokenRestrictionManager.primeRestrictionsCache('token')

            expect(dropEventSpy).toHaveBeenCalledWith('token')
            expect(skipPersonSpy).toHaveBeenCalledWith('token')
            expect(forceOverflowSpy).toHaveBeenCalledWith('token')
            expect(hub.redisPool.acquire).not.toHaveBeenCalled()
        })

        it('fetches cache values from Redis and stores them', async () => {
            pipelineMock.exec.mockResolvedValue([
                [null, 'drop-value'],
                [null, 'skip-value'],
                [null, 'overflow-value'],
            ])

            const dropEventSpy = jest.spyOn(tokenRestrictionManager['dropEventCache'], 'set')
            const skipPersonSpy = jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'set')
            const forceOverflowSpy = jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'set')

            await tokenRestrictionManager.primeRestrictionsCache('token')

            expect(hub.redisPool.acquire).toHaveBeenCalled()
            expect(pipelineMock.get).toHaveBeenCalledTimes(3)
            expect(pipelineMock.get).toHaveBeenCalledWith(`${RestrictionType.DROP_EVENT_FROM_INGESTION}:token`)
            expect(pipelineMock.get).toHaveBeenCalledWith(`${RestrictionType.SKIP_PERSON}:token`)
            expect(pipelineMock.get).toHaveBeenCalledWith(`${RestrictionType.FORCE_OVERFLOW_FROM_INGESTION}:token`)

            expect(dropEventSpy).toHaveBeenCalledWith('token', 'drop-value')
            expect(skipPersonSpy).toHaveBeenCalledWith('token', 'skip-value')
            expect(forceOverflowSpy).toHaveBeenCalledWith('token', 'overflow-value')

            expect(hub.redisPool.release).toHaveBeenCalledWith(redisClient)
        })

        it('handles null values from Redis correctly', async () => {
            pipelineMock.exec.mockResolvedValue([
                [null, null],
                [null, null],
                [null, null],
            ])

            const dropEventSpy = jest.spyOn(tokenRestrictionManager['dropEventCache'], 'set')
            const skipPersonSpy = jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'set')
            const forceOverflowSpy = jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'set')

            await tokenRestrictionManager.primeRestrictionsCache('token')

            expect(dropEventSpy).toHaveBeenCalledWith('token', null)
            expect(skipPersonSpy).toHaveBeenCalledWith('token', null)
            expect(forceOverflowSpy).toHaveBeenCalledWith('token', null)
        })

        it('handles Redis pipeline errors gracefully', async () => {
            const error = new Error('Redis error')
            pipelineMock.exec.mockRejectedValue(error)

            await tokenRestrictionManager.primeRestrictionsCache('token')

            expect(hub.redisPool.release).toHaveBeenCalledWith(redisClient)
        })
    })

    describe('shouldDropEvent', () => {
        it('returns false if token is not provided', () => {
            expect(tokenRestrictionManager.shouldDropEvent()).toBe(false)
        })

        it('returns true if token is in static drop list', () => {
            tokenRestrictionManager = new TokenRestrictionManager(hub as Hub, {
                dropEventTokens: ['static-drop-token'],
            })
            expect(tokenRestrictionManager.shouldDropEvent('static-drop-token')).toBe(true)
        })

        it('returns true if token:distinctId is in static drop list', () => {
            tokenRestrictionManager = new TokenRestrictionManager(hub as Hub, {
                dropEventTokens: ['static-drop-token:123'],
            })
            expect(tokenRestrictionManager.shouldDropEvent('static-drop-token', '123')).toBe(true)
        })

        it('returns false if Redis event filtering is disabled', () => {
            hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG = false
            expect(tokenRestrictionManager.shouldDropEvent('token')).toBe(false)
        })

        it('returns false if cache has a miss', () => {
            jest.spyOn(tokenRestrictionManager['dropEventCache'], 'get').mockReturnValue(null)
            expect(tokenRestrictionManager.shouldDropEvent('token')).toBe(false)
        })

        it('returns false if cache has undefined', () => {
            jest.spyOn(tokenRestrictionManager['dropEventCache'], 'get').mockReturnValue(undefined)
            expect(tokenRestrictionManager.shouldDropEvent('token')).toBe(false)
        })

        it('returns true if token is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['dropEventCache'], 'get').mockReturnValue('token')
            expect(tokenRestrictionManager.shouldDropEvent('token')).toBe(true)
        })

        it('returns true if distinctId is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['dropEventCache'], 'get').mockReturnValue('123,456')
            expect(tokenRestrictionManager.shouldDropEvent('token', '123')).toBe(true)
        })

        it('returns false if neither token nor distinctId is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['dropEventCache'], 'get').mockReturnValue('other-token,789')
            expect(tokenRestrictionManager.shouldDropEvent('token', '123')).toBe(false)
        })
    })
    describe('shouldSkipPerson', () => {
        it('returns false if token is not provided', () => {
            expect(tokenRestrictionManager.shouldSkipPerson()).toBe(false)
        })

        it('returns true if token is in static skip list', () => {
            tokenRestrictionManager = new TokenRestrictionManager(hub as Hub, {
                skipPersonTokens: ['static-skip-token'],
            })
            expect(tokenRestrictionManager.shouldSkipPerson('static-skip-token')).toBe(true)
        })

        it('returns true if token:distinctId is in static skip list', () => {
            tokenRestrictionManager = new TokenRestrictionManager(hub as Hub, {
                skipPersonTokens: ['static-skip-token:123'],
            })
            expect(tokenRestrictionManager.shouldSkipPerson('static-skip-token', '123')).toBe(true)
        })

        it('returns false if Redis event filtering is disabled', () => {
            hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG = false
            expect(tokenRestrictionManager.shouldSkipPerson('token')).toBe(false)
        })

        it('returns false if cache has a miss', () => {
            jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'get').mockReturnValue(null)
            expect(tokenRestrictionManager.shouldSkipPerson('token')).toBe(false)
        })

        it('returns false if cache has undefined', () => {
            jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'get').mockReturnValue(undefined)
            expect(tokenRestrictionManager.shouldSkipPerson('token')).toBe(false)
        })

        it('returns true if token is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'get').mockReturnValue('token')
            expect(tokenRestrictionManager.shouldSkipPerson('token')).toBe(true)
        })

        it('returns true if distinctId is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'get').mockReturnValue('123,456')
            expect(tokenRestrictionManager.shouldSkipPerson('token', '123')).toBe(true)
        })

        it('returns false if neither token nor distinctId is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'get').mockReturnValue('other-token,789')
            expect(tokenRestrictionManager.shouldSkipPerson('token', '123')).toBe(false)
        })
    })

    describe('shouldForceOverflow', () => {
        it('returns false if token is not provided', () => {
            expect(tokenRestrictionManager.shouldForceOverflow()).toBe(false)
        })

        it('returns true if token is in static overflow list', () => {
            tokenRestrictionManager = new TokenRestrictionManager(hub as Hub, {
                forceOverflowTokens: ['static-overflow-token'],
            })
            expect(tokenRestrictionManager.shouldForceOverflow('static-overflow-token')).toBe(true)
        })

        it('returns true if token:distinctId is in static overflow list', () => {
            tokenRestrictionManager = new TokenRestrictionManager(hub as Hub, {
                forceOverflowTokens: ['static-overflow-token:123'],
            })
            expect(tokenRestrictionManager.shouldForceOverflow('static-overflow-token', '123')).toBe(true)
        })

        it('returns false if Redis event filtering is disabled', () => {
            hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG = false
            expect(tokenRestrictionManager.shouldForceOverflow('token')).toBe(false)
        })

        it('returns false if cache has a miss', () => {
            jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'get').mockReturnValue(null)
            expect(tokenRestrictionManager.shouldForceOverflow('token')).toBe(false)
        })

        it('returns false if cache has undefined', () => {
            jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'get').mockReturnValue(undefined)
            expect(tokenRestrictionManager.shouldForceOverflow('token')).toBe(false)
        })

        it('returns true if token is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'get').mockReturnValue('token')
            expect(tokenRestrictionManager.shouldForceOverflow('token')).toBe(true)
        })

        it('returns true if distinctId is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'get').mockReturnValue('123,456')
            expect(tokenRestrictionManager.shouldForceOverflow('token', '123')).toBe(true)
        })

        it('returns false if neither token nor distinctId is in the cached blocked list', () => {
            jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'get').mockReturnValue('other-token,789')
            expect(tokenRestrictionManager.shouldForceOverflow('token', '123')).toBe(false)
        })
    })

    describe('clear', () => {
        it('clears all caches', () => {
            const dropEventSpy = jest.spyOn(tokenRestrictionManager['dropEventCache'], 'clear')
            const skipPersonSpy = jest.spyOn(tokenRestrictionManager['skipPersonCache'], 'clear')
            const forceOverflowSpy = jest.spyOn(tokenRestrictionManager['forceOverflowCache'], 'clear')

            tokenRestrictionManager.clear()

            expect(dropEventSpy).toHaveBeenCalled()
            expect(skipPersonSpy).toHaveBeenCalled()
            expect(forceOverflowSpy).toHaveBeenCalled()
        })
    })
})
