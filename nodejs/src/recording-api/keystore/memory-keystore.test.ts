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

        it('should return cleartext state for non-existent key', async () => {
            const result = await keyStore.getKey('new-session', 1)

            expect(result.sessionState).toBe('cleartext')
            expect(result.plaintextKey.length).toBe(0)
            expect(result.encryptedKey.length).toBe(0)
        })

        it('should return same key on subsequent calls', async () => {
            await keyStore.generateKey('session-123', 1)

            const first = await keyStore.getKey('session-123', 1)
            const second = await keyStore.getKey('session-123', 1)

            expect(first.plaintextKey.equals(second.plaintextKey)).toBe(true)
        })

        it('should return deleted state if key was deleted', async () => {
            await keyStore.generateKey('session-123', 1)
            await keyStore.deleteKey('session-123', 1)

            const result = await keyStore.getKey('session-123', 1)
            expect(result.sessionState).toBe('deleted')
            expect(result.plaintextKey.length).toBe(0)
            expect(result.encryptedKey.length).toBe(0)
        })

        it('should include deletedAt timestamp in deleted state', async () => {
            await keyStore.generateKey('session-123', 1)

            // Timestamps are in seconds
            const beforeDelete = Math.floor(Date.now() / 1000)
            await keyStore.deleteKey('session-123', 1)
            const afterDelete = Math.floor(Date.now() / 1000) + 1

            const result = await keyStore.getKey('session-123', 1)
            expect(result.sessionState).toBe('deleted')
            expect(result.deletedAt).toBeGreaterThanOrEqual(beforeDelete)
            expect(result.deletedAt).toBeLessThanOrEqual(afterDelete)
        })
    })

    describe('deleteKey', () => {
        it('should return deleted: true if key existed', async () => {
            await keyStore.generateKey('session-123', 1)
            const result = await keyStore.deleteKey('session-123', 1)

            expect(result).toEqual({ deleted: true })
        })

        it('should return not_found if key did not exist', async () => {
            const result = await keyStore.deleteKey('non-existent', 999)

            expect(result).toEqual({ deleted: false, reason: 'not_found' })
        })

        it('should return already_deleted with timestamp if key was already deleted', async () => {
            await keyStore.generateKey('session-123', 1)
            await keyStore.deleteKey('session-123', 1)

            const result = await keyStore.deleteKey('session-123', 1)

            expect(result.deleted).toBe(false)
            expect((result as any).reason).toBe('already_deleted')
            expect((result as any).deletedAt).toBeDefined()
        })

        it('should return deleted state on subsequent getKey calls', async () => {
            await keyStore.generateKey('session-123', 1)
            await keyStore.deleteKey('session-123', 1)

            const result = await keyStore.getKey('session-123', 1)
            expect(result.sessionState).toBe('deleted')
        })

        it('should not affect other sessions', async () => {
            await keyStore.generateKey('session-1', 1)
            await keyStore.generateKey('session-2', 1)

            await keyStore.deleteKey('session-1', 1)

            // session-2 should still be accessible
            const result = await keyStore.getKey('session-2', 1)
            expect(result.sessionState).toBe('ciphertext')

            // session-1 should return deleted state
            const deleted = await keyStore.getKey('session-1', 1)
            expect(deleted.sessionState).toBe('deleted')
        })

        it('should not affect same session id in different teams', async () => {
            await keyStore.generateKey('session-1', 1)
            await keyStore.generateKey('session-1', 2)

            await keyStore.deleteKey('session-1', 1)

            // Team 2 should still have access
            const result = await keyStore.getKey('session-1', 2)
            expect(result.sessionState).toBe('ciphertext')

            // Team 1 should return deleted state
            const deleted = await keyStore.getKey('session-1', 1)
            expect(deleted.sessionState).toBe('deleted')
        })
    })

    describe('stop', () => {
        it('should complete without error', () => {
            expect(() => keyStore.stop()).not.toThrow()
        })
    })
})
