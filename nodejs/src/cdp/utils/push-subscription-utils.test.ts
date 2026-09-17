import { EncryptedFields } from './encryption-utils'
import {
    MAX_DEVICE_TOKENS_PER_APP,
    deviceSubscriptionKey,
    getDevicePushSubscriptionToken,
    getDevicePushSubscriptions,
} from './push-subscription-utils'

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

describe('getDevicePushSubscriptions', () => {
    const encryptedFields = new EncryptedFields('01234567890123456789012345678901')
    const store = (appId: string, ...tokens: string[]): Record<string, string> =>
        Object.fromEntries(tokens.map((t) => [deviceSubscriptionKey(appId, t), encryptedFields.encrypt(t)]))

    it('returns every device registered for the app', () => {
        // The bug this fixes: a second device on the same app used to replace the first.
        const properties = store('my-project', 'token-phone', 'token-tablet')

        const tokens = getDevicePushSubscriptions(properties, 'my-project', encryptedFields).map((s) => s.token)

        expect(tokens.sort()).toEqual(['token-phone', 'token-tablet'])
    })

    it('still reads a device stored under the pre-per-device key', () => {
        // Devices registered before this change keep that key until they register again.
        const properties = {
            '$device_push_subscription_my-project': encryptedFields.encrypt('legacy-token'),
            ...store('my-project', 'new-token'),
        }

        const tokens = getDevicePushSubscriptions(properties, 'my-project', encryptedFields).map((s) => s.token)

        expect(tokens.sort()).toEqual(['legacy-token', 'new-token'])
    })

    it('sends once to a device holding the same token under both key shapes', () => {
        const token = 'same-token'
        const properties = {
            '$device_push_subscription_my-project': encryptedFields.encrypt(token),
            ...store('my-project', token),
        }

        expect(getDevicePushSubscriptions(properties, 'my-project', encryptedFields)).toHaveLength(1)
    })

    it('reports the key each token came from so one dead device can be pruned alone', () => {
        const properties = store('my-project', 'token-phone')

        const [subscription] = getDevicePushSubscriptions(properties, 'my-project', encryptedFields)

        expect(subscription.propertyKey).toBe(deviceSubscriptionKey('my-project', 'token-phone'))
    })

    it('ignores another app, including one whose name extends this one', () => {
        const properties = {
            ...store('my-project', 'mine'),
            ...store('my-project-staging', 'theirs'),
        }

        const tokens = getDevicePushSubscriptions(properties, 'my-project', encryptedFields).map((s) => s.token)

        expect(tokens).toEqual(['mine'])
    })

    it('skips a value that fails to decrypt but keeps the rest', () => {
        const properties = {
            ...store('my-project', 'good-token'),
            '$device_push_subscription_my-project:forged': 'not-encrypted-value',
        }

        const tokens = getDevicePushSubscriptions(properties, 'my-project', encryptedFields).map((s) => s.token)

        expect(tokens).toEqual(['good-token'])
    })

    it('caps how many devices one person and app can fan out to', () => {
        const tokens = Array.from({ length: MAX_DEVICE_TOKENS_PER_APP + 5 }, (_, i) => `token-${i}`)

        expect(getDevicePushSubscriptions(store('my-project', ...tokens), 'my-project', encryptedFields)).toHaveLength(
            MAX_DEVICE_TOKENS_PER_APP
        )
    })

    it('derives the same key the registration endpoint writes', () => {
        // Both sides hash the raw token; if they drift, a registration lands on a key sends never read.
        expect(deviceSubscriptionKey('my-project', 'device-token-abc123')).toBe(
            '$device_push_subscription_my-project:7d8d408df65cffa5'
        )
    })
})
