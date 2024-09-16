import { EncryptedFields } from '../../src/cdp/encryption-utils'
import { Hub } from '../../src/types'
import { insertHogFunction as _insertHogFunction } from './fixtures'

describe('Encrypted fields', () => {
    jest.setTimeout(1000)
    let encryptedFields: EncryptedFields

    const mockHub: Partial<Hub> = {
        DJANGO_ENCRYPTION_SECRET_KEYS: '<randomly generated secret key>',
        DJANGO_ENCRYPTION_SALT_KEYS: '0123456789abcdefghijklmnopqrstuvwxyz',
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
                'gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAEN-py1-Ob8hr3zEp5LsfNqusw0ovJsBR3jbfRxnBhPcv3xe1hmNpEPdNXU5Xv47OQ=='
            const decrypted = encryptedFields.decrypt(encrypted)
            expect(decrypted).toEqual('test-case')
        })
    })
})
