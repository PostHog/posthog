import { createHash } from 'crypto'

import { EncryptedFields } from './encryption-utils'

export const DEVICE_SUBSCRIPTION_PREFIX = '$device_push_subscription_'

/** Upper bound on devices addressed for one person and app in a single send. */
export const MAX_DEVICE_TOKENS_PER_APP = 20

export interface DeviceSubscription {
    /** Every person property holding this token, so a dead token is pruned from all of them at once.
     * A device can appear under both supported key shapes, and removing one would leave the other to
     * fail on the next send. */
    propertyKeys: string[]
    token: string
}

/** Person property key holding one device's push token. Mirrors `device_subscription_key` in
 * `push_subscriptions.py`; the two must agree or a registration lands on a key sends never read. */
export function deviceSubscriptionKey(appIdentifier: string, token: string): string {
    return `${DEVICE_SUBSCRIPTION_PREFIX}${appIdentifier}:${createHash('sha256')
        .update(token)
        .digest('hex')
        .slice(0, 16)}`
}

/**
 * Every device token registered for this person and app.
 *
 * Two key shapes carry a token. `<prefix><app>:<digest>` holds one device each. `<prefix><app>` holds
 * a single device for the whole app, and a device is reachable there until it next registers. Both
 * are read, so a person is addressed on every device whichever shape it is stored under.
 */
export function getDevicePushSubscriptions(
    personProperties: Record<string, any> | undefined,
    appIdentifier: string,
    encryptedFields: EncryptedFields
): DeviceSubscription[] {
    if (!personProperties) {
        return []
    }

    const legacyKey = `${DEVICE_SUBSCRIPTION_PREFIX}${appIdentifier}`
    const devicePrefix = `${legacyKey}:`
    const subscriptions: DeviceSubscription[] = []
    const seen = new Map<string, DeviceSubscription>()

    // Sorted so a person over the cap keeps the same devices from one send to the next, rather than
    // a set that shifts with property insertion order.
    for (const propertyKey of Object.keys(personProperties).sort()) {
        if (propertyKey !== legacyKey && !propertyKey.startsWith(devicePrefix)) {
            continue
        }
        const value = personProperties[propertyKey]
        if (!value || typeof value !== 'string') {
            continue
        }

        // Require successful decryption. The subscription endpoint always stores this token encrypted, so a
        // value that fails to decrypt was forged directly onto the person property via a plain `$set` capture
        // event (a raw token). Ignore it rather than delivering to an unverified device.
        let token: string | null = null
        try {
            token = encryptedFields.decrypt(value) ?? null
        } catch {
            continue
        }
        if (!token) {
            continue
        }
        // One device can hold the same token under both shapes, so send once and carry both keys.
        const existing = seen.get(token)
        if (existing) {
            existing.propertyKeys.push(propertyKey)
            continue
        }
        const subscription = { propertyKeys: [propertyKey], token }
        seen.set(token, subscription)
        subscriptions.push(subscription)
        if (subscriptions.length >= MAX_DEVICE_TOKENS_PER_APP) {
            break
        }
    }

    return subscriptions
}

/**
 * One device token for this person and app, or null.
 *
 * Kept for the `push_subscription` hog function input, whose value is a single token a template
 * reads. A person with several devices resolves to the first by key order.
 */
export function getDevicePushSubscriptionToken(
    personProperties: Record<string, any> | undefined,
    appIdentifier: string,
    encryptedFields: EncryptedFields
): string | null {
    return getDevicePushSubscriptions(personProperties, appIdentifier, encryptedFields)[0]?.token ?? null
}
