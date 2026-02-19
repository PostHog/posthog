import { KeyStore, SessionKey } from '../../types'
import { MemoryCachedKeyStore } from './memory-cache'

describe('MemoryCachedKeyStore', () => {
    let mockDelegate: jest.Mocked<KeyStore>
    let cachedKeyStore: MemoryCachedKeyStore

    const mockSessionKey: SessionKey = {
        plaintextKey: Buffer.from([1, 2, 3]),
        encryptedKey: Buffer.from([4, 5, 6]),
        sessionState: 'ciphertext',
    }

    beforeEach(() => {
        mockDelegate = {
            start: jest.fn().mockResolvedValue(undefined),
            generateKey: jest.fn().mockResolvedValue(mockSessionKey),
            getKey: jest.fn().mockResolvedValue(mockSessionKey),
            deleteKey: jest.fn().mockResolvedValue({ deleted: true }),
            stop: jest.fn(),
        } as unknown as jest.Mocked<KeyStore>

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
                sessionState: 'ciphertext',
            }
            const team2Key: SessionKey = {
                plaintextKey: Buffer.from([2, 2, 2]),
                encryptedKey: Buffer.from([2, 2, 2]),
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
        it('should clear cache and call delegate', async () => {
            // First, populate the cache
            await cachedKeyStore.getKey('session-123', 1)
            mockDelegate.getKey.mockClear()

            const result = await cachedKeyStore.deleteKey('session-123', 1)

            expect(mockDelegate.deleteKey).toHaveBeenCalledWith('session-123', 1)
            expect(result).toEqual({ deleted: true })

            // Cache should be cleared, so next getKey should call delegate
            await cachedKeyStore.getKey('session-123', 1)
            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
        })

        it('should clear cache even if delegate returns false', async () => {
            // First, populate the cache
            await cachedKeyStore.getKey('session-123', 1)
            mockDelegate.getKey.mockClear()

            mockDelegate.deleteKey.mockResolvedValue({ deleted: false, reason: 'not_found' })

            const result = await cachedKeyStore.deleteKey('session-123', 1)

            expect(result).toEqual({ deleted: false, reason: 'not_found' })

            // Cache should still be cleared
            await cachedKeyStore.getKey('session-123', 1)
            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
        })

        it('should propagate delegate deleteKey error', async () => {
            mockDelegate.deleteKey.mockRejectedValue(new Error('Delete failed'))

            await expect(cachedKeyStore.deleteKey('session-123', 1)).rejects.toThrow('Delete failed')
        })

        it('should only clear cache for the specified team', async () => {
            const team1Key: SessionKey = {
                plaintextKey: Buffer.from([1, 1, 1]),
                encryptedKey: Buffer.from([1, 1, 1]),
                sessionState: 'ciphertext',
            }
            const team2Key: SessionKey = {
                plaintextKey: Buffer.from([2, 2, 2]),
                encryptedKey: Buffer.from([2, 2, 2]),
                sessionState: 'ciphertext',
            }

            mockDelegate.getKey.mockResolvedValueOnce(team1Key).mockResolvedValueOnce(team2Key)

            // Populate cache for both teams
            await cachedKeyStore.getKey('session-123', 1)
            await cachedKeyStore.getKey('session-123', 2)
            mockDelegate.getKey.mockClear()

            // Delete only team 1's key
            await cachedKeyStore.deleteKey('session-123', 1)

            // Team 2's key should still be cached
            const result2 = await cachedKeyStore.getKey('session-123', 2)
            expect(mockDelegate.getKey).not.toHaveBeenCalled()
            expect(result2.plaintextKey).toEqual(Buffer.from([2, 2, 2]))

            // Team 1's key should require a delegate call
            mockDelegate.getKey.mockResolvedValueOnce(team1Key)
            await cachedKeyStore.getKey('session-123', 1)
            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
        })
    })

    describe('custom options', () => {
        it('should accept custom maxSize option', () => {
            const customCachedKeyStore = new MemoryCachedKeyStore(mockDelegate, { maxSize: 100 })

            expect(customCachedKeyStore).toBeInstanceOf(MemoryCachedKeyStore)
        })

        it('should expire cached items after ttlMs', async () => {
            const ttlMs = 50 // Short TTL for testing
            const customCachedKeyStore = new MemoryCachedKeyStore(mockDelegate, { ttlMs })

            // First call populates cache
            await customCachedKeyStore.getKey('session-123', 1)
            mockDelegate.getKey.mockClear()

            // Immediate second call should use cache
            await customCachedKeyStore.getKey('session-123', 1)
            expect(mockDelegate.getKey).not.toHaveBeenCalled()

            // Wait for TTL to expire
            await new Promise((resolve) => setTimeout(resolve, ttlMs + 10))

            // After TTL - should call delegate
            await customCachedKeyStore.getKey('session-123', 1)
            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
        })
    })

    describe('stop', () => {
        it('should call delegate stop', () => {
            cachedKeyStore.stop()

            expect(mockDelegate.stop).toHaveBeenCalled()
        })
    })
})
