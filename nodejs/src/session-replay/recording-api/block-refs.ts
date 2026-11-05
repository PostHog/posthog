import sodium from 'libsodium-wrappers'

import { parseJSON } from '~/common/utils/json-parse'

// A ref names a block without revealing its storage key: the location, encrypted with keys derived from the
// session key, under a nonce hashed from the location, so the same block always gets the same cacheable URL.
// Deriving from the session key is deliberate: shredding that key makes every ref for the session unreadable.
export interface BlockLocation {
    teamId: number
    sessionId: string
    key: string
    startByte: number
    endByte: number
}

const REF_VERSION = 'v1'
// crypto_kdf contexts are exactly 8 bytes.
const KDF_CONTEXT = 'blockref'
const ENCRYPTION_SUBKEY_ID = 1
const NONCE_SUBKEY_ID = 2

function encryptionKeyFor(sessionKey: Uint8Array): Uint8Array {
    return sodium.crypto_kdf_derive_from_key(
        sodium.crypto_secretbox_KEYBYTES,
        ENCRYPTION_SUBKEY_ID,
        KDF_CONTEXT,
        sessionKey
    )
}

function serialize(location: BlockLocation): Uint8Array {
    const { teamId, sessionId, key, startByte, endByte } = location
    return sodium.from_string(JSON.stringify([teamId, sessionId, key, startByte, endByte]))
}

// Derives the subkeys once, for naming every block of one listing. Callers must await sodium.ready first.
export function blockRefEncoder(sessionKey: Uint8Array): (location: BlockLocation) => string {
    const encryptionKey = encryptionKeyFor(sessionKey)
    const nonceKey = sodium.crypto_kdf_derive_from_key(
        sodium.crypto_generichash_KEYBYTES,
        NONCE_SUBKEY_ID,
        KDF_CONTEXT,
        sessionKey
    )
    return (location) => {
        const plaintext = serialize(location)
        const nonce = sodium.crypto_generichash(sodium.crypto_secretbox_NONCEBYTES, plaintext, nonceKey)
        const ciphertext = sodium.crypto_secretbox_easy(plaintext, nonce, encryptionKey)
        const payload = new Uint8Array(nonce.length + ciphertext.length)
        payload.set(nonce)
        payload.set(ciphertext, nonce.length)
        return `${REF_VERSION}.${sodium.to_base64(payload, sodium.base64_variants.URLSAFE_NO_PADDING)}`
    }
}

/** Returns null for any ref this session key did not produce for this team and session. */
export function decodeBlockRef(
    sessionKey: Uint8Array,
    ref: string,
    teamId: number,
    sessionId: string
): Omit<BlockLocation, 'teamId' | 'sessionId'> | null {
    const [version, encoded, ...rest] = ref.split('.')
    if (version !== REF_VERSION || !encoded || rest.length > 0) {
        return null
    }
    try {
        const payload = sodium.from_base64(encoded, sodium.base64_variants.URLSAFE_NO_PADDING)
        const nonce = payload.subarray(0, sodium.crypto_secretbox_NONCEBYTES)
        const ciphertext = payload.subarray(sodium.crypto_secretbox_NONCEBYTES)
        const plaintext = sodium.crypto_secretbox_open_easy(ciphertext, nonce, encryptionKeyFor(sessionKey))
        const [refTeamId, refSessionId, key, startByte, endByte] = parseJSON(sodium.to_string(plaintext))
        if (refTeamId !== teamId || refSessionId !== sessionId) {
            return null
        }
        if (typeof key !== 'string' || !Number.isInteger(startByte) || !Number.isInteger(endByte)) {
            return null
        }
        return { key, startByte, endByte }
    } catch {
        return null
    }
}
