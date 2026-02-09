import { KeyStore, SessionKey } from '../types'
import { RedisCachedKeyStore } from './redis-cache'

describe('RedisCachedKeyStore', () => {
    let mockDelegate: jest.Mocked<KeyStore>
    let mockRedisClient: any
    let mockRedisPool: any
    let cachedKeyStore: RedisCachedKeyStore

    const mockPlaintextKey = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    const mockEncryptedKey = new Uint8Array([101, 102, 103, 104, 105])

    const mockSessionKey: SessionKey = {
        plaintextKey: Buffer.from(mockPlaintextKey),
        encryptedKey: Buffer.from(mockEncryptedKey),
        sessionState: 'ciphertext',
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

        mockDelegate = {
            start: jest.fn().mockResolvedValue(undefined),
            generateKey: jest.fn().mockResolvedValue(mockSessionKey),
            getKey: jest.fn().mockResolvedValue(mockSessionKey),
            deleteKey: jest.fn().mockResolvedValue(true),
            stop: jest.fn(),
        } as unknown as jest.Mocked<KeyStore>

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
                sessionState: 'ciphertext',
            }
            const team2CachedKey = {
                plaintextKey: Buffer.from([2, 2, 2]).toString('base64'),
                encryptedKey: Buffer.from([2, 2, 2]).toString('base64'),
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
        it('should clear cache and call delegate', async () => {
            const result = await cachedKeyStore.deleteKey('session-123', 1)

            expect(mockRedisClient.del).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
            expect(mockDelegate.deleteKey).toHaveBeenCalledWith('session-123', 1)
            expect(result).toBe(true)
        })

        it('should clear cache even if delegate returns false', async () => {
            mockDelegate.deleteKey.mockResolvedValue(false)

            const result = await cachedKeyStore.deleteKey('session-123', 1)

            expect(mockRedisClient.del).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
            expect(result).toBe(false)
        })

        it('should propagate delegate deleteKey error', async () => {
            mockDelegate.deleteKey.mockRejectedValue(new Error('Delete failed'))

            await expect(cachedKeyStore.deleteKey('session-123', 1)).rejects.toThrow('Delete failed')
            expect(mockRedisClient.del).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
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
