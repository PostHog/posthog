import { SessionKeyDeletedError } from '../types'
import { MemoryKeyStore } from './memory-keystore'

describe('MemoryKeyStore', () => {
    let keyStore: MemoryKeyStore

    beforeEach(async () => {
        keyStore = new MemoryKeyStore()
        await keyStore.start()
    })

    describe('start', () => {
        it('should initialize sodium', async () => {
            const store = new MemoryKeyStore()
            await expect(store.start()).resolves.toBeUndefined()
        })
    })

    describe('generateKey', () => {
        it('should generate a key with ciphertext sessionState', async () => {
            const result = await keyStore.generateKey('session-123', 1)

            expect(result.sessionState).toBe('ciphertext')
            expect(result.plaintextKey).toBeInstanceOf(Buffer)
            expect(result.plaintextKey.length).toBe(32) // crypto_secretbox_KEYBYTES
            expect(result.encryptedKey).toEqual(result.plaintextKey)
        })

        it('should generate different keys for different sessions', async () => {
            const key1 = await keyStore.generateKey('session-1', 1)
            const key2 = await keyStore.generateKey('session-2', 1)

            expect(key1.plaintextKey.equals(key2.plaintextKey)).toBe(false)
        })

        it('should generate different keys for different teams with same session id', async () => {
            const key1 = await keyStore.generateKey('session-1', 1)
            const key2 = await keyStore.generateKey('session-1', 2)

            expect(key1.plaintextKey.equals(key2.plaintextKey)).toBe(false)
        })

        it('should overwrite existing key when called again', async () => {
            const key1 = await keyStore.generateKey('session-1', 1)
            const key2 = await keyStore.generateKey('session-1', 1)

            expect(key1.plaintextKey.equals(key2.plaintextKey)).toBe(false)

            // Verify getKey returns the new key
            const retrieved = await keyStore.getKey('session-1', 1)
            expect(retrieved.plaintextKey.equals(key2.plaintextKey)).toBe(true)
        })
    })

    describe('getKey', () => {
        it('should return existing key if previously generated', async () => {
            const generated = await keyStore.generateKey('session-123', 1)
            const retrieved = await keyStore.getKey('session-123', 1)

            expect(retrieved.plaintextKey.equals(generated.plaintextKey)).toBe(true)
            expect(retrieved.encryptedKey.equals(generated.encryptedKey)).toBe(true)
            expect(retrieved.sessionState).toBe('ciphertext')
        })

        it('should generate new key if not found', async () => {
            const result = await keyStore.getKey('new-session', 1)

            expect(result.sessionState).toBe('ciphertext')
            expect(result.plaintextKey.length).toBe(32)
        })

        it('should return same key on subsequent calls', async () => {
            const first = await keyStore.getKey('session-123', 1)
            const second = await keyStore.getKey('session-123', 1)

            expect(first.plaintextKey.equals(second.plaintextKey)).toBe(true)
        })

        it('should throw SessionKeyDeletedError if key was deleted', async () => {
            await keyStore.generateKey('session-123', 1)
            await keyStore.deleteKey('session-123', 1)

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow(SessionKeyDeletedError)
        })

        it('should include deletedAt timestamp in SessionKeyDeletedError', async () => {
            await keyStore.generateKey('session-123', 1)

            const beforeDelete = Date.now()
            await keyStore.deleteKey('session-123', 1)
            const afterDelete = Date.now()

            try {
                await keyStore.getKey('session-123', 1)
                fail('Expected SessionKeyDeletedError')
            } catch (error) {
                expect(error).toBeInstanceOf(SessionKeyDeletedError)
                const deletedError = error as SessionKeyDeletedError
                expect(deletedError.deletedAt).toBeGreaterThanOrEqual(beforeDelete)
                expect(deletedError.deletedAt).toBeLessThanOrEqual(afterDelete)
            }
        })
    })

    describe('deleteKey', () => {
        it('should return true if key existed', async () => {
            await keyStore.generateKey('session-123', 1)
            const result = await keyStore.deleteKey('session-123', 1)

            expect(result).toBe(true)
        })

        it('should return false if key did not exist', async () => {
            const result = await keyStore.deleteKey('non-existent', 999)

            expect(result).toBe(false)
        })

        it('should prevent subsequent getKey calls', async () => {
            await keyStore.generateKey('session-123', 1)
            await keyStore.deleteKey('session-123', 1)

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow(SessionKeyDeletedError)
        })

        it('should not affect other sessions', async () => {
            await keyStore.generateKey('session-1', 1)
            await keyStore.generateKey('session-2', 1)

            await keyStore.deleteKey('session-1', 1)

            // session-2 should still be accessible
            const result = await keyStore.getKey('session-2', 1)
            expect(result.sessionState).toBe('ciphertext')

            // session-1 should throw
            await expect(keyStore.getKey('session-1', 1)).rejects.toThrow(SessionKeyDeletedError)
        })

        it('should not affect same session id in different teams', async () => {
            await keyStore.generateKey('session-1', 1)
            await keyStore.generateKey('session-1', 2)

            await keyStore.deleteKey('session-1', 1)

            // Team 2 should still have access
            const result = await keyStore.getKey('session-1', 2)
            expect(result.sessionState).toBe('ciphertext')

            // Team 1 should throw
            await expect(keyStore.getKey('session-1', 1)).rejects.toThrow(SessionKeyDeletedError)
        })
    })

    describe('stop', () => {
        it('should complete without error', () => {
            expect(() => keyStore.stop()).not.toThrow()
        })
    })
})
