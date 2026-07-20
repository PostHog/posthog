import { EncryptedFields } from './encryption-utils'
import { getDevicePushSubscriptionToken } from './push-subscription-utils'

describe('getDevicePushSubscriptionToken', () => {
    const encryptedFields = new EncryptedFields('01234567890123456789012345678901')

    it('returns null when person properties are undefined', () => {
        expect(getDevicePushSubscriptionToken(undefined, 'my-project', encryptedFields)).toBeNull()
    })

    it('returns null when the property is missing', () => {
        expect(getDevicePushSubscriptionToken({}, 'my-project', encryptedFields)).toBeNull()
    })

    it('returns null when the property value is not a string', () => {
        expect(
            getDevicePushSubscriptionToken({ $device_push_subscription_my_project: 123 }, 'my_project', encryptedFields)
        ).toBeNull()
    })

    it('decrypts and returns the token for the matching app identifier', () => {
        const token = 'device-token-abc123'
        const encrypted = encryptedFields.encrypt(token)
        const properties = {
            [`$device_push_subscription_my-project`]: encrypted,
        }

        expect(getDevicePushSubscriptionToken(properties, 'my-project', encryptedFields)).toBe(token)
    })

    it('returns null for a non-matching app identifier', () => {
        const encrypted = encryptedFields.encrypt('device-token-abc123')
        const properties = {
            $device_push_subscription_other_project: encrypted,
        }

        expect(getDevicePushSubscriptionToken(properties, 'my-project', encryptedFields)).toBeNull()
    })

    it('returns null when the stored value fails to decrypt (a forged plaintext token is rejected)', () => {
        const properties = {
            [`$device_push_subscription_my-project`]: 'not-encrypted-value',
        }

        expect(getDevicePushSubscriptionToken(properties, 'my-project', encryptedFields)).toBeNull()
    })
})
