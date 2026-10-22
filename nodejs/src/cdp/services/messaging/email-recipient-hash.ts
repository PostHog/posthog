import { createHmac } from 'node:crypto'

// Django derives the same hash to look emails up by recipient. Changing any part of this changes
// every hash already stored, so a change needs a new purpose string, not an edit to this one.
const RECIPIENT_HASH_PURPOSE = 'email-recipient-hash-v1'

const firstSaltKey = (encryptionSaltKeys: string): string => {
    const key = encryptionSaltKeys.split(',')[0].trim()
    if (!key) {
        throw new Error('ENCRYPTION_SALT_KEYS is not set, so email recipients cannot be hashed')
    }
    return key
}

const hmacSha256 = (key: string | Buffer, message: string): Buffer => createHmac('sha256', key).update(message).digest()

export function emailRecipientHash(address: string, encryptionSaltKeys: string): string {
    const recipientKey = hmacSha256(firstSaltKey(encryptionSaltKeys), RECIPIENT_HASH_PURPOSE)
    return hmacSha256(recipientKey, address.trim().toLowerCase()).toString('hex')
}
