import { parseJSON } from '../utils/json-parse'
import { deserializeSessionKey, serializeSessionKey } from './session-key'

describe('session-key serialization', () => {
    describe('serializeSessionKey', () => {
        it.each([
            {
                name: 'ciphertext session key',
                input: {
                    plaintextKey: Buffer.from([1, 2, 3, 4, 5]),
                    encryptedKey: Buffer.from([10, 20, 30, 40, 50]),
                    nonce: Buffer.from([100, 101, 102]),
                    sessionState: 'ciphertext' as const,
                },
                expected: {
                    plaintextKey: 'AQIDBAU=',
                    encryptedKey: 'ChQeKDI=',
                    nonce: 'ZGVm',
                    sessionState: 'ciphertext',
                },
            },
            {
                name: 'cleartext session key',
                input: {
                    plaintextKey: Buffer.alloc(0),
                    encryptedKey: Buffer.alloc(0),
                    nonce: Buffer.alloc(0),
                    sessionState: 'cleartext' as const,
                },
                expected: {
                    plaintextKey: '',
                    encryptedKey: '',
                    nonce: '',
                    sessionState: 'cleartext',
                },
            },
            {
                name: 'deleted session key with deletedAt',
                input: {
                    plaintextKey: Buffer.alloc(0),
                    encryptedKey: Buffer.alloc(0),
                    nonce: Buffer.alloc(0),
                    sessionState: 'deleted' as const,
                    deletedAt: 1234567890,
                },
                expected: {
                    plaintextKey: '',
                    encryptedKey: '',
                    nonce: '',
                    sessionState: 'deleted',
                    deletedAt: 1234567890,
                },
            },
            {
                name: 'deleted session key without deletedAt',
                input: {
                    plaintextKey: Buffer.alloc(0),
                    encryptedKey: Buffer.alloc(0),
                    nonce: Buffer.alloc(0),
                    sessionState: 'deleted' as const,
                },
                expected: {
                    plaintextKey: '',
                    encryptedKey: '',
                    nonce: '',
                    sessionState: 'deleted',
                },
            },
        ])('should serialize $name', ({ input, expected }) => {
            const result = serializeSessionKey(input)
            const parsed = parseJSON(result)

            expect(parsed.plaintextKey).toBe(expected.plaintextKey)
            expect(parsed.encryptedKey).toBe(expected.encryptedKey)
            expect(parsed.nonce).toBe(expected.nonce)
            expect(parsed.sessionState).toBe(expected.sessionState)
            expect(parsed.deletedAt).toBe(expected.deletedAt)
        })
    })

    describe('deserializeSessionKey', () => {
        it.each([
            {
                name: 'ciphertext session key',
                input: {
                    plaintextKey: 'AQIDBAU=',
                    encryptedKey: 'ChQeKDI=',
                    nonce: 'ZGVm',
                    sessionState: 'ciphertext' as const,
                },
                expected: {
                    plaintextKey: Buffer.from([1, 2, 3, 4, 5]),
                    encryptedKey: Buffer.from([10, 20, 30, 40, 50]),
                    nonce: Buffer.from([100, 101, 102]),
                    sessionState: 'ciphertext',
                },
            },
            {
                name: 'cleartext session key',
                input: {
                    plaintextKey: '',
                    encryptedKey: '',
                    nonce: '',
                    sessionState: 'cleartext' as const,
                },
                expected: {
                    plaintextKey: Buffer.alloc(0),
                    encryptedKey: Buffer.alloc(0),
                    nonce: Buffer.alloc(0),
                    sessionState: 'cleartext',
                },
            },
            {
                name: 'deleted session key with deletedAt',
                input: {
                    plaintextKey: '',
                    encryptedKey: '',
                    nonce: '',
                    sessionState: 'deleted' as const,
                    deletedAt: 1234567890,
                },
                expected: {
                    plaintextKey: Buffer.alloc(0),
                    encryptedKey: Buffer.alloc(0),
                    nonce: Buffer.alloc(0),
                    sessionState: 'deleted',
                    deletedAt: 1234567890,
                },
            },
            {
                name: 'deleted session key without deletedAt',
                input: {
                    plaintextKey: '',
                    encryptedKey: '',
                    nonce: '',
                    sessionState: 'deleted' as const,
                },
                expected: {
                    plaintextKey: Buffer.alloc(0),
                    encryptedKey: Buffer.alloc(0),
                    nonce: Buffer.alloc(0),
                    sessionState: 'deleted',
                    deletedAt: undefined,
                },
            },
        ])('should deserialize $name', ({ input, expected }) => {
            const result = deserializeSessionKey(JSON.stringify(input))

            expect(result.plaintextKey).toEqual(expected.plaintextKey)
            expect(result.encryptedKey).toEqual(expected.encryptedKey)
            expect(result.nonce).toEqual(expected.nonce)
            expect(result.sessionState).toBe(expected.sessionState)
            expect(result.deletedAt).toBe(expected.deletedAt)
        })
    })

    describe('roundtrip', () => {
        it.each([
            {
                name: 'ciphertext session key',
                key: {
                    plaintextKey: Buffer.from([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]),
                    encryptedKey: Buffer.from([101, 102, 103, 104, 105]),
                    nonce: Buffer.from([201, 202, 203, 204, 205, 206, 207, 208]),
                    sessionState: 'ciphertext' as const,
                },
            },
            {
                name: 'cleartext session key',
                key: {
                    plaintextKey: Buffer.alloc(0),
                    encryptedKey: Buffer.alloc(0),
                    nonce: Buffer.alloc(0),
                    sessionState: 'cleartext' as const,
                },
            },
            {
                name: 'deleted session key with deletedAt',
                key: {
                    plaintextKey: Buffer.alloc(0),
                    encryptedKey: Buffer.alloc(0),
                    nonce: Buffer.alloc(0),
                    sessionState: 'deleted' as const,
                    deletedAt: 1234567890,
                },
            },
        ])('should roundtrip $name', ({ key }) => {
            const serialized = serializeSessionKey(key)
            const deserialized = deserializeSessionKey(serialized)

            expect(deserialized.plaintextKey).toEqual(key.plaintextKey)
            expect(deserialized.encryptedKey).toEqual(key.encryptedKey)
            expect(deserialized.nonce).toEqual(key.nonce)
            expect(deserialized.sessionState).toBe(key.sessionState)
            expect(deserialized.deletedAt).toBe(key.deletedAt)
        })
    })
})
