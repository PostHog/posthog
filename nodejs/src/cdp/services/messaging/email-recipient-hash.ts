import { createHmac } from 'node:crypto'

// Django derives the same hash to look emails up by recipient. Changing any part of this changes
// every hash already stored, so a change needs a new purpose string, not an edit to this one.
const RECIPIENT_HASH_PURPOSE = 'email-recipient-hash-v1'

const firstSaltKey = (encryptionSaltKeys: string): string | undefined =>
    encryptionSaltKeys.split(',')[0].trim() || undefined

const hmacSha256 = (key: string | Buffer, message: string): Buffer => createHmac('sha256', key).update(message).digest()

const hashUnder = (saltKey: string, address: string): string =>
    hmacSha256(hmacSha256(saltKey, RECIPIENT_HASH_PURPOSE), address.trim().toLowerCase()).toString('hex')

// Undefined without a salt key, so the caller skips only the status write and still sends.
export function emailRecipientHash(address: string, encryptionSaltKeys: string): string | undefined {
    const saltKey = firstSaltKey(encryptionSaltKeys)
    return saltKey ? hashUnder(saltKey, address) : undefined
}

// Every key, because an email sent before a key rotation carries the hash of a key that is no longer first.
export function emailRecipientHashes(address: string, encryptionSaltKeys: string): string[] {
    return encryptionSaltKeys
        .split(',')
        .map((saltKey) => saltKey.trim())
        .filter(Boolean)
        .map((saltKey) => hashUnder(saltKey, address))
}
