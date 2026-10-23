import { createHmac } from 'node:crypto'

// Django derives the same hash to look emails up by recipient. Changing any part of this changes
// every hash already stored, so a change needs a new purpose string, not an edit to this one.
const RECIPIENT_HASH_PURPOSE = 'email-recipient-hash-v1'

const firstSaltKey = (encryptionSaltKeys: string): string | undefined =>
    encryptionSaltKeys.split(',')[0].trim() || undefined

const hmacSha256 = (key: string | Buffer, message: string): Buffer => createHmac('sha256', key).update(message).digest()

// Undefined without a salt key, so the caller skips only the status write and still sends.
export function emailRecipientHash(address: string, encryptionSaltKeys: string): string | undefined {
    const saltKey = firstSaltKey(encryptionSaltKeys)
    if (!saltKey) {
        return undefined
    }
    const recipientKey = hmacSha256(saltKey, RECIPIENT_HASH_PURPOSE)
    return hmacSha256(recipientKey, address.trim().toLowerCase()).toString('hex')
}
