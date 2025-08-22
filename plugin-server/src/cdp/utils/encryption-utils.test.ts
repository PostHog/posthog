import { Hub } from '../../types'
import { EncryptedFields } from './encryption-utils'

describe('Encrypted fields', () => {
    jest.setTimeout(1000)
    let encryptedFields: EncryptedFields

    const mockHub: Partial<Hub> = {
        ENCRYPTION_SALT_KEYS: '00beef0000beef0000beef0000beef00',
    }

    beforeEach(() => {
        encryptedFields = new EncryptedFields(mockHub as unknown as Hub)
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
