import { EncryptedFields } from '../../src/cdp/encryption-utils'
import { Hub } from '../../src/types'
import { insertHogFunction as _insertHogFunction } from './fixtures'

describe('Encrypted fields', () => {
    jest.setTimeout(1000)
    let encryptedFields: EncryptedFields

    const mockHub: Partial<Hub> = {
        ENCRYPTION_SALT_KEYS: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ012345',
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
                'gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAFoHDFl5z8lrvd6QPZj0FC-Hxr567WC_EQxa95EGyjRwCJ94LDuO4y7PzhSE77D0hA=='
            const decrypted = encryptedFields.decrypt(encrypted)
            expect(decrypted).toEqual('test-case')
        })
    })
})
