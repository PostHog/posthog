import { KeyStore, SessionKey } from '../types'
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
            deleteKey: jest.fn().mockResolvedValue(true),
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
        it('should call delegate and update cache with deleted state including deletedAt', async () => {
            const deletedKey: SessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
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

        it('should remove stale cache entry if getKey fails after successful delete', async () => {
            // First, populate the cache
            await cachedKeyStore.getKey('session-123', 1)
            mockDelegate.getKey.mockClear()

            // Verify cache is populated
            await cachedKeyStore.getKey('session-123', 1)
            expect(mockDelegate.getKey).not.toHaveBeenCalled()

            // Now make getKey fail after deleteKey succeeds
            mockDelegate.getKey.mockRejectedValue(new Error('Get failed after delete'))

            const result = await cachedKeyStore.deleteKey('session-123', 1)

            // deleteKey should still return true
            expect(result).toBe(true)

            // Cache should be cleared, so next getKey should call delegate
            mockDelegate.getKey.mockResolvedValue(mockSessionKey)
            mockDelegate.getKey.mockClear()

            await cachedKeyStore.getKey('session-123', 1)
            expect(mockDelegate.getKey).toHaveBeenCalledWith('session-123', 1)
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
