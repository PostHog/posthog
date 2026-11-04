import { parseJSON } from '~/common/utils/json-parse'
import { SessionBatchMetrics } from '~/ingestion/pipelines/sessionreplay/sessions/metrics'
import { KeyStore, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { RedisCachedKeyStore } from './redis-cache'

jest.mock('~/ingestion/pipelines/sessionreplay/sessions/metrics', () => ({
    SessionBatchMetrics: {
        observeKeystoreRedisLatency: jest.fn(),
        incrementKeystoreRedisWriteErrors: jest.fn(),
    },
}))

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
            set: jest.fn().mockResolvedValue('OK'),
            eval: jest.fn().mockResolvedValue(1),
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
            deleteKey: jest
                .fn()
                .mockResolvedValue({ status: 'deleted', deletedAt: 1700000000, deletedBy: 'test@example.com' }),
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
            const result = await cachedKeyStore.generateKey('session-123', 1, 30)

            expect(mockDelegate.generateKey).toHaveBeenCalledWith('session-123', 1, 30)
            expect(mockRedisPool.acquire).toHaveBeenCalled()
            expect(mockRedisClient.eval).toHaveBeenCalledWith(
                expect.stringContaining("'deleted'"),
                1,
                '@posthog/replay/recording-key:1:session-123',
                expect.any(String),
                86400
            )
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
            expect(result).toEqual(mockSessionKey)
        })

        it('should propagate delegate generateKey error', async () => {
            mockDelegate.generateKey.mockRejectedValue(new Error('Generate failed'))

            await expect(cachedKeyStore.generateKey('session-123', 1, 30)).rejects.toThrow('Generate failed')
        })

        it('should return the key and release Redis client if the cache write fails', async () => {
            mockRedisClient.eval.mockRejectedValue(new Error("READONLY You can't write against a read only replica."))

            const result = await cachedKeyStore.generateKey('session-123', 1, 30)

            expect(result).toEqual(mockSessionKey)
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
            expect(SessionBatchMetrics.incrementKeystoreRedisWriteErrors).toHaveBeenCalled()
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
            expect(mockRedisClient.set).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                expect.any(String),
                'EX',
                86400,
                'NX'
            )
            expect(result).toEqual(mockSessionKey)
        })

        it.each([
            ['caches', 'ciphertext' as const, 1],
            ['skips caching', 'cleartext' as const, 0],
        ])('%s a %s key when built not to cache a missing key', async (_, sessionState, expectedWrites) => {
            mockRedisClient.get.mockResolvedValue(null)
            mockDelegate.getKey.mockResolvedValue({ ...mockSessionKey, sessionState })
            const store = new RedisCachedKeyStore(mockDelegate, mockRedisPool, undefined, false)

            await store.getKey('session-123', 1)

            expect(mockRedisClient.set).toHaveBeenCalledTimes(expectedWrites)
        })

        it.each([
            ['set rejects', () => mockRedisClient.set.mockRejectedValue(new Error('READONLY'))],
            [
                'pool acquire rejects',
                () =>
                    mockRedisPool.acquire
                        .mockResolvedValueOnce(mockRedisClient)
                        .mockRejectedValueOnce(new Error('acquire timeout')),
            ],
        ])('should return the delegate key on Redis miss when %s', async (_, setup) => {
            mockRedisClient.get.mockResolvedValue(null)
            setup()

            const result = await cachedKeyStore.getKey('session-123', 1)

            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
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
            const result = await cachedKeyStore.deleteKey('session-123', 1, 'test@example.com')

            expect(mockRedisClient.del).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
            expect(mockDelegate.deleteKey).toHaveBeenCalledWith('session-123', 1, 'test@example.com')
            expect(result).toEqual({ status: 'deleted', deletedAt: 1700000000, deletedBy: 'test@example.com' })
        })

        const useInMemoryRedis = (): void => {
            const store = new Map<string, string>()
            mockRedisClient.get.mockImplementation((key: string) => Promise.resolve(store.get(key) ?? null))
            mockRedisClient.del.mockImplementation((key: string) => Promise.resolve(store.delete(key) ? 1 : 0))
            mockRedisClient.setex.mockImplementation((key: string, _ttl: number, value: string) => {
                store.set(key, value)
                return Promise.resolve('OK')
            })
            mockRedisClient.set.mockImplementation((key: string, value: string, ...flags: unknown[]) => {
                if (flags.includes('NX') && store.has(key)) {
                    return Promise.resolve(null)
                }
                store.set(key, value)
                return Promise.resolve('OK')
            })
            // The unless-deleted script: write unless the entry holds a deletion marker.
            mockRedisClient.eval.mockImplementation((_script: string, _n: number, key: string, value: string) => {
                const current = store.get(key)
                if (current && parseJSON(current).sessionState === 'deleted') {
                    return Promise.resolve(0)
                }
                store.set(key, value)
                return Promise.resolve(1)
            })
        }

        it('keeps the deletion when a lookup that read the live key finishes after the delete', async () => {
            useInMemoryRedis()
            let releaseLookup: (key: SessionKey) => void = () => {}
            mockDelegate.getKey.mockImplementation(() => new Promise((resolve) => (releaseLookup = resolve)))

            const lookup = cachedKeyStore.getKey('session-123', 1)
            await new Promise((resolve) => setImmediate(resolve))
            await cachedKeyStore.deleteKey('session-123', 1, 'test@example.com')
            releaseLookup(mockSessionKey)
            await lookup

            mockDelegate.getKey.mockClear()
            const after = await cachedKeyStore.getKey('session-123', 1)
            expect(after.sessionState).toBe('deleted')
            expect(mockDelegate.getKey).not.toHaveBeenCalled()
        })

        it('keeps the deletion when a key generation finishes caching after the delete', async () => {
            useInMemoryRedis()
            let releaseGeneration: (key: SessionKey) => void = () => {}
            mockDelegate.generateKey.mockImplementation(() => new Promise((resolve) => (releaseGeneration = resolve)))

            const generation = cachedKeyStore.generateKey('session-123', 1, 30)
            await new Promise((resolve) => setImmediate(resolve))
            await cachedKeyStore.deleteKey('session-123', 1, 'test@example.com')
            releaseGeneration(mockSessionKey)
            await generation

            mockDelegate.getKey.mockClear()
            const after = await cachedKeyStore.getKey('session-123', 1)
            expect(after.sessionState).toBe('deleted')
            expect(mockDelegate.getKey).not.toHaveBeenCalled()
        })

        it('lets a new key replace a cached missing key', async () => {
            useInMemoryRedis()
            mockDelegate.getKey.mockResolvedValue({ ...mockSessionKey, sessionState: 'cleartext' })
            await cachedKeyStore.getKey('session-123', 1)

            await cachedKeyStore.generateKey('session-123', 1, 30)

            mockDelegate.getKey.mockClear()
            expect((await cachedKeyStore.getKey('session-123', 1)).sessionState).toBe('ciphertext')
        })

        it('reports a committed deletion even when the cache cannot record it', async () => {
            mockRedisClient.setex.mockRejectedValue(new Error('READONLY'))

            const result = await cachedKeyStore.deleteKey('session-123', 1, 'test@example.com')

            expect(result).toEqual({ status: 'deleted', deletedAt: 1700000000, deletedBy: 'test@example.com' })
            expect(SessionBatchMetrics.incrementKeystoreRedisWriteErrors).toHaveBeenCalled()
        })

        it('should clear cache even if delegate returns already_deleted', async () => {
            mockDelegate.deleteKey.mockResolvedValue({
                status: 'already_deleted',
                deletedAt: 1700000000,
                deletedBy: 'original@example.com',
            })

            const result = await cachedKeyStore.deleteKey('session-123', 1, 'test@example.com')

            expect(mockRedisClient.del).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
            expect(result).toEqual({
                status: 'already_deleted',
                deletedAt: 1700000000,
                deletedBy: 'original@example.com',
            })
        })

        it('should propagate delegate deleteKey error', async () => {
            mockDelegate.deleteKey.mockRejectedValue(new Error('Delete failed'))

            await expect(cachedKeyStore.deleteKey('session-123', 1, 'test@example.com')).rejects.toThrow(
                'Delete failed'
            )
            expect(mockRedisClient.del).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
        })

        it('should fail and not call delegate if cache clear fails', async () => {
            mockRedisClient.del.mockRejectedValue(new Error('READONLY'))

            await expect(cachedKeyStore.deleteKey('session-123', 1, 'test@example.com')).rejects.toThrow('READONLY')
            expect(mockDelegate.deleteKey).not.toHaveBeenCalled()
        })

        it('should only clear cache for the specified team', async () => {
            await cachedKeyStore.deleteKey('session-123', 1, 'test@example.com')

            // Should only delete team 1's cache key
            expect(mockRedisClient.del).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
            expect(mockRedisClient.del).not.toHaveBeenCalledWith('@posthog/replay/recording-key:2:session-123')
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

            await customTtlCachedKeyStore.generateKey('session-123', 1, 30)

            expect(mockRedisClient.eval).toHaveBeenCalledWith(
                expect.any(String),
                1,
                '@posthog/replay/recording-key:1:session-123',
                expect.any(String),
                3600
            )
        })
    })
})
