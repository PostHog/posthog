import { parseJSON } from '../utils/json-parse'
import { SerializedSessionKey, SessionKey } from './types'

export function serializeSessionKey(key: SessionKey): string {
    const serialized: SerializedSessionKey = {
        plaintextKey: key.plaintextKey.toString('base64'),
        encryptedKey: key.encryptedKey.toString('base64'),
        nonce: key.nonce.toString('base64'),
        sessionState: key.sessionState,
        deletedAt: key.deletedAt,
    }
    return JSON.stringify(serialized)
}

export function deserializeSessionKey(json: string): SessionKey {
    const parsed = parseJSON(json) as SerializedSessionKey
    return {
        plaintextKey: Buffer.from(parsed.plaintextKey, 'base64'),
        encryptedKey: Buffer.from(parsed.encryptedKey, 'base64'),
        nonce: Buffer.from(parsed.nonce, 'base64'),
        sessionState: parsed.sessionState,
        deletedAt: parsed.deletedAt,
    }
}
