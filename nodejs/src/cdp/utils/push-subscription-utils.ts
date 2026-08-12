import { EncryptedFields } from './encryption-utils'

/**
 * Extract the device token from the $device_push_subscription_<appIdentifier> person property.
 *
 * The property value is the encrypted device token.
 * Returns the decrypted token, or null if the property is missing or fails to decrypt.
 */
export function getDevicePushSubscriptionToken(
    personProperties: Record<string, any> | undefined,
    appIdentifier: string,
    encryptedFields: EncryptedFields
): string | null {
    const value = personProperties?.[`$device_push_subscription_${appIdentifier}`]
    if (!value || typeof value !== 'string') {
        return null
    }

    // Require successful decryption. The subscription endpoint always stores this token encrypted, so a
    // value that fails to decrypt was forged directly onto the person property via a plain `$set` capture
    // event (a raw token). Ignore it rather than delivering to an unverified device.
    try {
        return encryptedFields.decrypt(value) ?? null
    } catch {
        return null
    }
}
