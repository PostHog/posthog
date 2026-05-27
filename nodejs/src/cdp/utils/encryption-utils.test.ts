import { EncryptedFields, INLINE_ENCRYPTED_MARKER } from './encryption-utils'

describe('Encrypted fields', () => {
    jest.setTimeout(1000)
    let encryptedFields: EncryptedFields

    const encryptionSaltKeys = '00beef0000beef0000beef0000beef00'

    beforeEach(() => {
        encryptedFields = new EncryptedFields(encryptionSaltKeys)
    })

    it('should construct with empty keys but throw on encrypt/decrypt', () => {
        const empty = new EncryptedFields('')
        expect(() => empty.encrypt('test')).toThrow('Encryption keys are not set')
        expect(() => empty.decrypt('test')).toThrow('Encryption keys are not set')
    })

    describe('encryption and decryption', () => {
        it('should encrypt and decrypt a string', () => {
            const encrypted = encryptedFields.encrypt('test-case')
            expect(encrypted).not.toEqual('test-case')
            const decrypted = encryptedFields.decrypt(encrypted)
            expect(decrypted).toEqual('test-case')
        })

        it('should decode django example', () => {
            const encrypted =
                'gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAP89mTGU6xUyLcVUIB4ySnX2Y8ZgwLALpzYGfm76Fk64vPRY62flSIigMa_MqTlKyA=='
            const decrypted = encryptedFields.decrypt(encrypted)
            expect(decrypted).toEqual('test-case')
        })

        it('should throw on decryption error', () => {
            expect(() => encryptedFields.decrypt('NOT VALID')).toThrow()
        })

        it('should not throw on decryption error if option passed', () => {
            expect(() => encryptedFields.decrypt('NOT VALID', { ignoreDecryptionErrors: true })).not.toThrow()
            expect(encryptedFields.decrypt('NOT VALID', { ignoreDecryptionErrors: true })).toEqual('NOT VALID')
        })

        describe('decryptInlineInputs', () => {
            const encryptValue = (value: unknown): { [INLINE_ENCRYPTED_MARKER]: string } => ({
                [INLINE_ENCRYPTED_MARKER]: encryptedFields.encrypt(JSON.stringify(value)),
            })

            const schema = [
                { key: 'url', secret: false },
                { key: 'access_token', secret: true },
            ]

            it('decrypts inline-encrypted secret inputs and leaves others alone', () => {
                const inputs = {
                    url: { value: 'https://example.com', order: 0 },
                    access_token: { value: encryptValue('super-secret'), order: 1 },
                }

                const decrypted = encryptedFields.decryptInlineInputs(inputs as any, schema)
                expect(decrypted).toEqual({
                    url: { value: 'https://example.com', order: 0 },
                    access_token: { value: 'super-secret', order: 1 },
                })
            })

            it('returns undefined/null untouched', () => {
                expect(encryptedFields.decryptInlineInputs(undefined as any, schema)).toBeUndefined()
                expect(encryptedFields.decryptInlineInputs(null as any, schema)).toBeNull()
            })

            it('throws when the encrypted token is invalid', () => {
                const inputs = { access_token: { value: { [INLINE_ENCRYPTED_MARKER]: 'NOT_VALID_TOKEN' } } }
                expect(() => encryptedFields.decryptInlineInputs(inputs as any, schema)).toThrow()
            })

            it('does not decrypt an inline-encrypted blob placed in a non-secret input', () => {
                // Defends against using a non-secret input as a decryption oracle: even with a
                // valid encrypted token, the value passes through untouched when the schema does
                // not flag that key as `secret: true`.
                const encryptedBlob = encryptValue('would-be-leaked')
                const inputs = {
                    url: { value: encryptedBlob, order: 0 },
                    access_token: { value: encryptValue('real-secret'), order: 1 },
                }

                const decrypted = encryptedFields.decryptInlineInputs(inputs as any, schema)
                expect(decrypted).toEqual({
                    url: { value: encryptedBlob, order: 0 },
                    access_token: { value: 'real-secret', order: 1 },
                })
            })

            it('decrypts nothing when schema is missing or has no secret keys', () => {
                const inputs = {
                    access_token: { value: encryptValue('untouched'), order: 0 },
                }

                expect(encryptedFields.decryptInlineInputs(inputs as any, undefined)).toEqual(inputs)
                expect(encryptedFields.decryptInlineInputs(inputs as any, [])).toEqual(inputs)
                expect(
                    encryptedFields.decryptInlineInputs(inputs as any, [{ key: 'access_token', secret: false }])
                ).toEqual(inputs)
            })
        })

        describe('decrypting objects', () => {
            it('should decrypt an object', () => {
                const exampleObject = {
                    key: encryptedFields.encrypt('value'),
                    missing: null,
                    nested: {
                        key: encryptedFields.encrypt('nested-value'),
                    },
                }
                expect(encryptedFields.decryptObject(exampleObject)).toEqual({
                    key: 'value',
                    missing: null,
                    nested: {
                        key: 'nested-value',
                    },
                })
            })

            it('should throw on decryption error', () => {
                expect(() =>
                    encryptedFields.decryptObject({
                        key: 'NOT VALID',
                    })
                ).toThrow()
            })

            it('should not throw on decryption error if option passed', () => {
                const exampleObject = {
                    key: 'not encrypted',
                    missing: null,
                    nested: {
                        key: 'also not encrypted',
                    },
                }
                expect(() =>
                    encryptedFields.decryptObject(exampleObject, { ignoreDecryptionErrors: true })
                ).not.toThrow()
                expect(encryptedFields.decryptObject(exampleObject, { ignoreDecryptionErrors: true })).toEqual(
                    exampleObject
                )
            })
        })
    })
})
