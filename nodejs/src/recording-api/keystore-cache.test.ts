import { MemoryCachedKeyStore, RedisCachedKeyStore } from './keystore-cache'
import { BaseKeyStore, SessionKey } from './types'

describe('MemoryCachedKeyStore', () => {
    let mockDelegate: jest.Mocked<BaseKeyStore>
    let cachedKeyStore: MemoryCachedKeyStore

    const mockSessionKey: SessionKey = {
        plaintextKey: Buffer.from([1, 2, 3]),
        encryptedKey: Buffer.from([4, 5, 6]),
        nonce: Buffer.from([7, 8, 9]),
        sessionState: 'ciphertext',
    }

    beforeEach(() => {
        mockDelegate = {
            start: jest.fn().mockResolvedValue(undefined),
            generateKey: jest.fn().mockResolvedValue(mockSessionKey),
            getKey: jest.fn().mockResolvedValue(mockSessionKey),
            deleteKey: jest.fn().mockResolvedValue(true),
            stop: jest.fn(),
        } as unknown as jest.Mocked<BaseKeyStore>

        cachedKeyStore = new MemoryCachedKeyStore(mockDelegate)
    })

    describe('start', () => {
        it('should call delegate start', async () => {
            await cachedKeyStore.start()

            expect(mockDelegate.start).toHaveBeenCalled()
        })

        it('should propagate delegate start error', async () => {
            mockDelegate.start.mockRejectedValue(new Error('Start failed'))

            await expect(cachedKeyStore.start()).rejects.toThrow('Start failed')
        })
    })

    describe('generateKey', () => {
        it('should call delegate and cache the result', async () => {
            const result = await cachedKeyStore.generateKey('session-123', 1)

            expect(mockDelegate.generateKey).toHaveBeenCalledWith('session-123', 1)
            expect(result).toEqual(mockSessionKey)

            // Second call should use cache
            mockDelegate.getKey.mockClear()
            const cachedResult = await cachedKeyStore.getKey('session-123', 1)

            expect(mockDelegate.getKey).not.toHaveBeenCalled()
            expect(cachedResult).toEqual(mockSessionKey)
        })

        it('should propagate delegate generateKey error', async () => {
            mockDelegate.generateKey.mockRejectedValue(new Error('Generate failed'))

            await expect(cachedKeyStore.generateKey('session-123', 1)).rejects.toThrow('Generate failed')
        })
    })

    describe('getKey', () => {
        it('should call delegate on cache miss', async () => {
            const result = await cachedKeyStore.getKey('session-123', 1)

            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
            expect(result).toEqual(mockSessionKey)
        })

        it('should return cached value on cache hit', async () => {
            // First call populates cache
            await cachedKeyStore.getKey('session-123', 1)
            mockDelegate.getKey.mockClear()

            // Second call should use cache
            const result = await cachedKeyStore.getKey('session-123', 1)

            expect(mockDelegate.getKey).not.toHaveBeenCalled()
            expect(result).toEqual(mockSessionKey)
        })

        it('should propagate delegate getKey error', async () => {
            mockDelegate.getKey.mockRejectedValue(new Error('Get failed'))

            await expect(cachedKeyStore.getKey('session-123', 1)).rejects.toThrow('Get failed')
        })

        it('should isolate cache entries by teamId', async () => {
            const team1Key: SessionKey = {
                plaintextKey: Buffer.from([1, 1, 1]),
                encryptedKey: Buffer.from([1, 1, 1]),
                nonce: Buffer.from([1, 1, 1]),
                sessionState: 'ciphertext',
            }
            const team2Key: SessionKey = {
                plaintextKey: Buffer.from([2, 2, 2]),
                encryptedKey: Buffer.from([2, 2, 2]),
                nonce: Buffer.from([2, 2, 2]),
                sessionState: 'ciphertext',
            }

            mockDelegate.getKey.mockResolvedValueOnce(team1Key).mockResolvedValueOnce(team2Key)

            // Same sessionId, different teams
            const result1 = await cachedKeyStore.getKey('session-123', 1)
            const result2 = await cachedKeyStore.getKey('session-123', 2)

            expect(result1.plaintextKey).toEqual(Buffer.from([1, 1, 1]))
            expect(result2.plaintextKey).toEqual(Buffer.from([2, 2, 2]))
            expect(mockDelegate.getKey).toHaveBeenCalledTimes(2)

            // Verify cache isolation - should return cached values
            mockDelegate.getKey.mockClear()
            const cachedResult1 = await cachedKeyStore.getKey('session-123', 1)
            const cachedResult2 = await cachedKeyStore.getKey('session-123', 2)

            expect(cachedResult1.plaintextKey).toEqual(Buffer.from([1, 1, 1]))
            expect(cachedResult2.plaintextKey).toEqual(Buffer.from([2, 2, 2]))
            expect(mockDelegate.getKey).not.toHaveBeenCalled()
        })
    })

    describe('deleteKey', () => {
        it('should call delegate and update cache with deleted state including deletedAt', async () => {
            const deletedKey: SessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'deleted',
                deletedAt: 1234567890,
            }
            mockDelegate.getKey.mockResolvedValue(deletedKey)

            const result = await cachedKeyStore.deleteKey('session-123', 1)

            expect(mockDelegate.deleteKey).toHaveBeenCalledWith('session-123', 1)
            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
            expect(result).toBe(true)

            // Subsequent getKey should return deleted state from cache with deletedAt preserved
            mockDelegate.getKey.mockClear()
            const cachedResult = await cachedKeyStore.getKey('session-123', 1)

            expect(mockDelegate.getKey).not.toHaveBeenCalled()
            expect(cachedResult.sessionState).toBe('deleted')
            expect(cachedResult.deletedAt).toBe(1234567890)
        })

        it('should not update cache if delegate returns false', async () => {
            mockDelegate.deleteKey.mockResolvedValue(false)

            const result = await cachedKeyStore.deleteKey('session-123', 1)

            expect(result).toBe(false)

            // getKey should still call delegate since cache wasn't updated
            await cachedKeyStore.getKey('session-123', 1)
            expect(mockDelegate.getKey).toHaveBeenCalled()
        })

        it('should propagate delegate deleteKey error', async () => {
            mockDelegate.deleteKey.mockRejectedValue(new Error('Delete failed'))

            await expect(cachedKeyStore.deleteKey('session-123', 1)).rejects.toThrow('Delete failed')
        })
    })

    describe('custom options', () => {
        it('should accept custom maxSize option', () => {
            const customCachedKeyStore = new MemoryCachedKeyStore(mockDelegate, { maxSize: 100 })

            expect(customCachedKeyStore).toBeInstanceOf(MemoryCachedKeyStore)
        })

        it('should accept custom ttlMs option', () => {
            const customCachedKeyStore = new MemoryCachedKeyStore(mockDelegate, { ttlMs: 1000 })

            expect(customCachedKeyStore).toBeInstanceOf(MemoryCachedKeyStore)
        })
    })

    describe('stop', () => {
        it('should call delegate stop', () => {
            cachedKeyStore.stop()

            expect(mockDelegate.stop).toHaveBeenCalled()
        })
    })
})

describe('RedisCachedKeyStore', () => {
    let mockDelegate: jest.Mocked<BaseKeyStore>
    let mockRedisClient: any
    let mockRedisPool: any
    let cachedKeyStore: RedisCachedKeyStore

    const mockPlaintextKey = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    const mockEncryptedKey = new Uint8Array([101, 102, 103, 104, 105])
    const mockNonce = new Uint8Array([201, 202, 203, 204, 205, 206, 207, 208])

    const mockSessionKey: SessionKey = {
        plaintextKey: Buffer.from(mockPlaintextKey),
        encryptedKey: Buffer.from(mockEncryptedKey),
        nonce: Buffer.from(mockNonce),
        sessionState: 'ciphertext',
    }

    beforeEach(() => {
        mockRedisClient = {
            get: jest.fn().mockResolvedValue(null),
            setex: jest.fn().mockResolvedValue('OK'),
        }

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn().mockResolvedValue(undefined),
        }

        mockDelegate = {
            start: jest.fn().mockResolvedValue(undefined),
            generateKey: jest.fn().mockResolvedValue(mockSessionKey),
            getKey: jest.fn().mockResolvedValue(mockSessionKey),
            deleteKey: jest.fn().mockResolvedValue(true),
            stop: jest.fn(),
        } as unknown as jest.Mocked<BaseKeyStore>

        cachedKeyStore = new RedisCachedKeyStore(mockDelegate, mockRedisPool)
    })

    describe('start', () => {
        it('should call delegate start', async () => {
            await cachedKeyStore.start()

            expect(mockDelegate.start).toHaveBeenCalled()
        })

        it('should propagate delegate start error', async () => {
            mockDelegate.start.mockRejectedValue(new Error('Start failed'))

            await expect(cachedKeyStore.start()).rejects.toThrow('Start failed')
        })
    })

    describe('generateKey', () => {
        it('should call delegate and cache in Redis', async () => {
            const result = await cachedKeyStore.generateKey('session-123', 1)

            expect(mockDelegate.generateKey).toHaveBeenCalledWith('session-123', 1)
            expect(mockRedisPool.acquire).toHaveBeenCalled()
            expect(mockRedisClient.setex).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                86400,
                expect.any(String)
            )
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
            expect(result).toEqual(mockSessionKey)
        })

        it('should propagate delegate generateKey error', async () => {
            mockDelegate.generateKey.mockRejectedValue(new Error('Generate failed'))

            await expect(cachedKeyStore.generateKey('session-123', 1)).rejects.toThrow('Generate failed')
        })

        it('should release Redis client even if setex fails', async () => {
            mockRedisClient.setex.mockRejectedValue(new Error('Redis setex failed'))

            await expect(cachedKeyStore.generateKey('session-123', 1)).rejects.toThrow('Redis setex failed')
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
        })
    })

    describe('getKey', () => {
        it('should return cached value from Redis on cache hit', async () => {
            const cachedKey = {
                plaintextKey: Buffer.from(mockPlaintextKey).toString('base64'),
                encryptedKey: Buffer.from(mockEncryptedKey).toString('base64'),
                nonce: Buffer.from(mockNonce).toString('base64'),
                sessionState: 'ciphertext',
            }
            mockRedisClient.get.mockResolvedValue(JSON.stringify(cachedKey))

            const result = await cachedKeyStore.getKey('session-123', 1)

            expect(mockRedisPool.acquire).toHaveBeenCalled()
            expect(mockRedisClient.get).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
            expect(mockDelegate.getKey).not.toHaveBeenCalled()
            expect(result.plaintextKey).toEqual(Buffer.from(mockPlaintextKey))
        })

        it('should call delegate and cache on Redis miss', async () => {
            mockRedisClient.get.mockResolvedValue(null)

            const result = await cachedKeyStore.getKey('session-123', 1)

            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
            expect(mockRedisClient.setex).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                86400,
                expect.any(String)
            )
            expect(result).toEqual(mockSessionKey)
        })

        it('should propagate delegate getKey error', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            mockDelegate.getKey.mockRejectedValue(new Error('Get failed'))

            await expect(cachedKeyStore.getKey('session-123', 1)).rejects.toThrow('Get failed')
        })

        it('should release Redis client even if get fails', async () => {
            mockRedisClient.get.mockRejectedValue(new Error('Redis get failed'))

            await expect(cachedKeyStore.getKey('session-123', 1)).rejects.toThrow('Redis get failed')
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
        })

        it('should isolate cache entries by teamId', async () => {
            const team1CachedKey = {
                plaintextKey: Buffer.from([1, 1, 1]).toString('base64'),
                encryptedKey: Buffer.from([1, 1, 1]).toString('base64'),
                nonce: Buffer.from([1, 1, 1]).toString('base64'),
                sessionState: 'ciphertext',
            }
            const team2CachedKey = {
                plaintextKey: Buffer.from([2, 2, 2]).toString('base64'),
                encryptedKey: Buffer.from([2, 2, 2]).toString('base64'),
                nonce: Buffer.from([2, 2, 2]).toString('base64'),
                sessionState: 'ciphertext',
            }

            mockRedisClient.get
                .mockResolvedValueOnce(JSON.stringify(team1CachedKey))
                .mockResolvedValueOnce(JSON.stringify(team2CachedKey))

            const result1 = await cachedKeyStore.getKey('session-123', 1)
            const result2 = await cachedKeyStore.getKey('session-123', 2)

            expect(mockRedisClient.get).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
            expect(mockRedisClient.get).toHaveBeenCalledWith('@posthog/replay/recording-key:2:session-123')
            expect(result1.plaintextKey).toEqual(Buffer.from([1, 1, 1]))
            expect(result2.plaintextKey).toEqual(Buffer.from([2, 2, 2]))
        })
    })

    describe('deleteKey', () => {
        it('should call delegate and update Redis cache with deleted state including deletedAt', async () => {
            const deletedKey: SessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'deleted',
                deletedAt: 1234567890,
            }
            mockDelegate.getKey.mockResolvedValue(deletedKey)

            const result = await cachedKeyStore.deleteKey('session-123', 1)

            expect(mockDelegate.deleteKey).toHaveBeenCalledWith('session-123', 1)
            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
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
            expect(result).toBe(true)
        })

        it('should not update Redis cache if delegate returns false', async () => {
            mockDelegate.deleteKey.mockResolvedValue(false)

            const result = await cachedKeyStore.deleteKey('session-123', 1)

            expect(result).toBe(false)
            expect(mockRedisClient.setex).not.toHaveBeenCalled()
        })

        it('should propagate delegate deleteKey error', async () => {
            mockDelegate.deleteKey.mockRejectedValue(new Error('Delete failed'))

            await expect(cachedKeyStore.deleteKey('session-123', 1)).rejects.toThrow('Delete failed')
        })
    })

    describe('stop', () => {
        it('should call delegate stop', () => {
            cachedKeyStore.stop()

            expect(mockDelegate.stop).toHaveBeenCalled()
        })
    })

    describe('custom TTL', () => {
        it('should use custom TTL when provided', async () => {
            const customTtlCachedKeyStore = new RedisCachedKeyStore(mockDelegate, mockRedisPool, 3600)

            await customTtlCachedKeyStore.generateKey('session-123', 1)

            expect(mockRedisClient.setex).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                3600,
                expect.any(String)
            )
        })
    })
})

describe('Combined MemoryCachedKeyStore and RedisCachedKeyStore', () => {
    let mockBaseDelegate: jest.Mocked<BaseKeyStore>
    let mockRedisClient: any
    let mockRedisPool: any
    let combinedKeyStore: MemoryCachedKeyStore

    const mockSessionKey: SessionKey = {
        plaintextKey: Buffer.from([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]),
        encryptedKey: Buffer.from([101, 102, 103, 104, 105]),
        nonce: Buffer.from([201, 202, 203, 204, 205, 206, 207, 208]),
        sessionState: 'ciphertext',
    }

    const mockDeletedKey: SessionKey = {
        plaintextKey: Buffer.alloc(0),
        encryptedKey: Buffer.alloc(0),
        nonce: Buffer.alloc(0),
        sessionState: 'deleted',
        deletedAt: 1234567890,
    }

    beforeEach(() => {
        mockRedisClient = {
            get: jest.fn().mockResolvedValue(null),
            setex: jest.fn().mockResolvedValue('OK'),
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
        } as unknown as jest.Mocked<BaseKeyStore>

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
                nonce: mockSessionKey.nonce.toString('base64'),
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
                nonce: Buffer.alloc(0).toString('base64'),
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
