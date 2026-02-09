import { KeyStore, SessionKey } from '../types'
import { MemoryCachedKeyStore } from './memory-cache'
import { RedisCachedKeyStore } from './redis-cache'

describe('Combined MemoryCachedKeyStore and RedisCachedKeyStore', () => {
    let mockBaseDelegate: jest.Mocked<KeyStore>
    let mockRedisClient: any
    let mockRedisPool: any
    let combinedKeyStore: MemoryCachedKeyStore

    const mockSessionKey: SessionKey = {
        plaintextKey: Buffer.from([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]),
        encryptedKey: Buffer.from([101, 102, 103, 104, 105]),
        sessionState: 'ciphertext',
    }

    const mockDeletedKey: SessionKey = {
        plaintextKey: Buffer.alloc(0),
        encryptedKey: Buffer.alloc(0),
        sessionState: 'deleted',
        deletedAt: 1234567890,
    }

    beforeEach(() => {
        mockRedisClient = {
            get: jest.fn().mockResolvedValue(null),
            setex: jest.fn().mockResolvedValue('OK'),
            del: jest.fn().mockResolvedValue(1),
        }

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn().mockResolvedValue(undefined),
        }

        mockBaseDelegate = {
            start: jest.fn().mockResolvedValue(undefined),
            generateKey: jest.fn().mockResolvedValue(mockSessionKey),
            getKey: jest.fn().mockResolvedValue(mockSessionKey),
            deleteKey: jest.fn().mockResolvedValue(true),
            stop: jest.fn(),
        } as unknown as jest.Mocked<KeyStore>

        const redisCachedKeyStore = new RedisCachedKeyStore(mockBaseDelegate, mockRedisPool)
        combinedKeyStore = new MemoryCachedKeyStore(redisCachedKeyStore)
    })

    describe('cache hierarchy', () => {
        it('should check memory cache first, then Redis, then delegate', async () => {
            // First call - all caches miss, hits delegate
            const result1 = await combinedKeyStore.getKey('session-123', 1)

            expect(mockRedisClient.get).toHaveBeenCalledTimes(1)
            expect(mockBaseDelegate.getKey).toHaveBeenCalledTimes(1)
            expect(result1).toEqual(mockSessionKey)

            // Second call - memory cache hit, no Redis or delegate call
            mockRedisClient.get.mockClear()
            mockBaseDelegate.getKey.mockClear()

            const result2 = await combinedKeyStore.getKey('session-123', 1)

            expect(mockRedisClient.get).not.toHaveBeenCalled()
            expect(mockBaseDelegate.getKey).not.toHaveBeenCalled()
            expect(result2).toEqual(mockSessionKey)
        })

        it('should populate memory cache from Redis cache hit', async () => {
            const cachedKey = {
                plaintextKey: mockSessionKey.plaintextKey.toString('base64'),
                encryptedKey: mockSessionKey.encryptedKey.toString('base64'),
                sessionState: 'ciphertext',
            }
            mockRedisClient.get.mockResolvedValue(JSON.stringify(cachedKey))

            // First call - memory miss, Redis hit
            const result1 = await combinedKeyStore.getKey('session-123', 1)

            expect(mockRedisClient.get).toHaveBeenCalledTimes(1)
            expect(mockBaseDelegate.getKey).not.toHaveBeenCalled()
            expect(result1.sessionState).toBe('ciphertext')

            // Second call - memory hit
            mockRedisClient.get.mockClear()

            const result2 = await combinedKeyStore.getKey('session-123', 1)

            expect(mockRedisClient.get).not.toHaveBeenCalled()
            expect(result2.sessionState).toBe('ciphertext')
        })
    })

    describe('deleteKey with combined caches', () => {
        it('should propagate delete through all layers and preserve deletedAt', async () => {
            mockBaseDelegate.getKey.mockResolvedValue(mockDeletedKey)

            const result = await combinedKeyStore.deleteKey('session-123', 1)

            expect(mockBaseDelegate.deleteKey).toHaveBeenCalledWith('session-123', 1)
            expect(result).toBe(true)

            // Verify Redis was updated with deleted state including deletedAt
            expect(mockRedisClient.setex).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                86400,
                expect.stringContaining('"sessionState":"deleted"')
            )
            expect(mockRedisClient.setex).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                86400,
                expect.stringContaining('"deletedAt":1234567890')
            )

            // Subsequent getKey should return from memory cache with deletedAt preserved
            mockRedisClient.get.mockClear()
            mockBaseDelegate.getKey.mockClear()

            const cachedResult = await combinedKeyStore.getKey('session-123', 1)

            expect(mockRedisClient.get).not.toHaveBeenCalled()
            expect(mockBaseDelegate.getKey).not.toHaveBeenCalled()
            expect(cachedResult.sessionState).toBe('deleted')
            expect(cachedResult.deletedAt).toBe(1234567890)
        })

        it('should fetch deleted state from Redis when memory cache is empty', async () => {
            const deletedCachedKey = {
                plaintextKey: Buffer.alloc(0).toString('base64'),
                encryptedKey: Buffer.alloc(0).toString('base64'),
                sessionState: 'deleted',
                deletedAt: 1234567890,
            }
            mockRedisClient.get.mockResolvedValue(JSON.stringify(deletedCachedKey))

            // Simulate fresh instance (empty memory cache) reading deleted key from Redis
            const freshRedisCachedKeyStore = new RedisCachedKeyStore(mockBaseDelegate, mockRedisPool)
            const freshCombinedKeyStore = new MemoryCachedKeyStore(freshRedisCachedKeyStore)

            const result = await freshCombinedKeyStore.getKey('session-123', 1)

            expect(mockRedisClient.get).toHaveBeenCalledTimes(1)
            expect(mockBaseDelegate.getKey).not.toHaveBeenCalled()
            expect(result.sessionState).toBe('deleted')
            expect(result.deletedAt).toBe(1234567890)
        })
    })

    describe('generateKey with combined caches', () => {
        it('should populate both caches on generateKey', async () => {
            const result = await combinedKeyStore.generateKey('session-123', 1)

            expect(mockBaseDelegate.generateKey).toHaveBeenCalledWith('session-123', 1)
            expect(mockRedisClient.setex).toHaveBeenCalled()
            expect(result).toEqual(mockSessionKey)

            // Subsequent getKey should hit memory cache
            mockRedisClient.get.mockClear()
            mockBaseDelegate.getKey.mockClear()

            const cachedResult = await combinedKeyStore.getKey('session-123', 1)

            expect(mockRedisClient.get).not.toHaveBeenCalled()
            expect(mockBaseDelegate.getKey).not.toHaveBeenCalled()
            expect(cachedResult).toEqual(mockSessionKey)
        })
    })
})
