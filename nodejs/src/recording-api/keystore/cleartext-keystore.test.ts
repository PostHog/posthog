import { CleartextKeyStore } from './cleartext-keystore'

describe('CleartextKeyStore', () => {
    let keyStore: CleartextKeyStore

    beforeEach(() => {
        keyStore = new CleartextKeyStore()
    })

    describe('start', () => {
        it('should complete without error', async () => {
            await expect(keyStore.start()).resolves.toBeUndefined()
        })
    })

    describe('generateKey', () => {
        it('should return empty keys with sessionState cleartext', async () => {
            const result = await keyStore.generateKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.sessionState).toBe('cleartext')
        })
    })

    describe('getKey', () => {
        it('should return empty keys with sessionState cleartext', async () => {
            const result = await keyStore.getKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.sessionState).toBe('cleartext')
        })
    })

    describe('deleteKey', () => {
        it('should throw error since crypto-shredding is not supported', async () => {
            await expect(keyStore.deleteKey('session-123', 1)).rejects.toThrow(
                'Recording deletion is not supported for cleartext sessions'
            )
        })
    })

    describe('stop', () => {
        it('should complete without error', () => {
            expect(() => keyStore.stop()).not.toThrow()
        })
    })
})
