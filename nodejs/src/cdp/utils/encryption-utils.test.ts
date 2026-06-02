import { EncryptedFields } from './encryption-utils'

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

        describe('two-step key rotation', () => {
            // Apps are not guaranteed to redeploy simultaneously, so rotation is done in two steps:
            //   step 1: [OLD] -> [OLD, NEW]      NEW added for decryption; OLD still encrypts
            //   step 2: [OLD, NEW] -> [NEW, OLD] NEW now encrypts; OLD kept for decryption
            // Safety invariant: within each step's mixed-version window, every running app can
            // decrypt whatever any other running app writes.
            const OLD = 'o'.repeat(32)
            const NEW = 'n'.repeat(32)
            const PLAINTEXT = 'super-secret-value'

            const app = (keys: string[]): EncryptedFields => new EncryptedFields(keys.join(','))

            it.each([
                ['step 1', [[OLD], [OLD, NEW]]],
                [
                    'step 2',
                    [
                        [OLD, NEW],
                        [NEW, OLD],
                    ],
                ],
            ])('%s: coexisting apps decrypt each others writes', (_name, coexisting) => {
                for (const writerKeys of coexisting) {
                    const token = app(writerKeys).encrypt(PLAINTEXT)
                    for (const readerKeys of coexisting) {
                        expect(app(readerKeys).decrypt(token)).toEqual(PLAINTEXT)
                    }
                }
            })

            it.each([
                ['old only', [OLD]],
                ['old then new', [OLD, NEW]],
            ])('step 1 (%s) always encrypts with the old key', (_name, keys) => {
                const token = app(keys).encrypt(PLAINTEXT)
                expect(app([OLD]).decrypt(token)).toEqual(PLAINTEXT)
                expect(() => app([NEW]).decrypt(token)).toThrow()
            })

            it('step 2 apps encrypt with the new key', () => {
                const token = app([NEW, OLD]).encrypt(PLAINTEXT)
                expect(app([NEW]).decrypt(token)).toEqual(PLAINTEXT)
            })

            it('skipping step 1 would break un-upgraded apps', () => {
                const token = app([NEW, OLD]).encrypt(PLAINTEXT)
                expect(() => app([OLD]).decrypt(token)).toThrow()
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
