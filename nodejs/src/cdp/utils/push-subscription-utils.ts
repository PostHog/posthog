import { createHash } from 'crypto'

import { EncryptedFields } from './encryption-utils'

export const DEVICE_SUBSCRIPTION_PREFIX = '$device_push_subscription_'

/** Upper bound on devices addressed for one person and app in a single send. */
export const MAX_DEVICE_TOKENS_PER_APP = 20

export interface DeviceSubscription {
    /** Person property holding this token, so a dead token can be pruned on its own. */
    propertyKey: string
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
 * Two key shapes are read. `<prefix><app>` is what every client wrote before tokens were keyed per
 * device, and a device that has not registered since still lives there. `<prefix><app>:<digest>` is
 * one key per device. Both are returned so a fix on the write side reaches devices already stored.
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
    const seen = new Set<string>()

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
        if (!token || seen.has(token)) {
            // A device registered before this change holds the same token under both shapes until the
            // legacy key is pruned, so dedupe on the token to avoid sending twice.
            continue
        }
        seen.add(token)
        subscriptions.push({ propertyKey, token })
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
