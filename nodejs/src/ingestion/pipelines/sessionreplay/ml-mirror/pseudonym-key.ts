/** Resolves the pseudonymization key (KMS-wrapped in prod, plaintext env for local dev) and pins it against rotation. */
import { DecryptCommand, KMSClient } from '@aws-sdk/client-kms'
import { createHmac } from 'crypto'

import { logger } from '~/common/utils/logger'

export interface PseudonymKeyConfig {
    SESSION_RECORDING_ML_PSEUDONYM_SECRET: string
    SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY: string
    SESSION_RECORDING_ML_PSEUDONYM_KMS_REGION: string
    SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT: string
}

/** Decrypts a base64 KMS-wrapped key; injectable so tests don't hit KMS. */
export type KeyDecryptor = (ciphertextBase64: string, region: string) => Promise<Buffer>

const kmsDecrypt: KeyDecryptor = async (ciphertextBase64, region) => {
    const client = new KMSClient(region ? { region } : {})
    const result = await client.send(new DecryptCommand({ CiphertextBlob: Buffer.from(ciphertextBase64, 'base64') }))
    if (!result.Plaintext) {
        throw new Error('KMS Decrypt returned no plaintext for the pseudonym key')
    }
    return Buffer.from(result.Plaintext)
}

/**
 * Non-reversible, domain-separated fingerprint of the key. Safe to log/store: it identifies the key without
 * revealing it, so the dataset's identity space can be pinned to one key.
 */
export function pseudonymKeyFingerprint(secret: string | Buffer): string {
    return createHmac('sha256', secret).update('pseudonym-key-fingerprint:v1').digest('hex').slice(0, 16)
}

/**
 * Resolves the HMAC key: prefers the KMS-wrapped ciphertext (decrypted once, never persisted), else the plaintext
 * env secret (local dev). Fails closed when no key is configured, or when a pinned fingerprint doesn't match the
 * resolved key — a changed key would re-map every id and contaminate train/eval splits, so we refuse to start.
 */
export async function resolvePseudonymKey(
    config: PseudonymKeyConfig,
    decrypt: KeyDecryptor = kmsDecrypt
): Promise<string | Buffer> {
    let secret: string | Buffer
    let source: 'kms' | 'env'
    if (config.SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY) {
        secret = await decrypt(
            config.SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY,
            config.SESSION_RECORDING_ML_PSEUDONYM_KMS_REGION
        )
        source = 'kms'
    } else if (config.SESSION_RECORDING_ML_PSEUDONYM_SECRET) {
        secret = config.SESSION_RECORDING_ML_PSEUDONYM_SECRET
        source = 'env'
    } else {
        throw new Error(
            'SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY or SESSION_RECORDING_ML_PSEUDONYM_SECRET must be set for the ML mirror'
        )
    }

    const fingerprint = pseudonymKeyFingerprint(secret)
    const expected = config.SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT
    if (expected && expected !== fingerprint) {
        throw new Error(
            `pseudonym key fingerprint mismatch (resolved ${fingerprint}, expected ${expected}) — refusing to start: ` +
                'a rotated/incorrect key would re-map ids and contaminate train/eval splits'
        )
    }

    logger.info('🔑', 'ml_pseudonym_key_loaded', { source, fingerprint, pinned: Boolean(expected) })
    return secret
}
