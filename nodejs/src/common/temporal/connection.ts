import type { DataConverter, TLSConfig } from '@temporalio/client'
import fs from 'fs/promises'

import { logger } from '~/common/utils/logger'

import { EncryptionCodec } from './codec'

export type TemporalConnectionConfig = {
    TEMPORAL_CLIENT_ROOT_CA: string | undefined
    TEMPORAL_CLIENT_CERT: string | undefined
    TEMPORAL_CLIENT_KEY: string | undefined
    TEMPORAL_SECRET_KEY: string | undefined
    TEMPORAL_FALLBACK_SECRET_KEYS: string
}

export async function buildTemporalTLSConfig(config: TemporalConnectionConfig): Promise<TLSConfig | false> {
    const { TEMPORAL_CLIENT_ROOT_CA, TEMPORAL_CLIENT_CERT, TEMPORAL_CLIENT_KEY } = config
    if (!(TEMPORAL_CLIENT_ROOT_CA && TEMPORAL_CLIENT_CERT && TEMPORAL_CLIENT_KEY)) {
        return false
    }

    let systemCAs = Buffer.alloc(0)
    try {
        systemCAs = Buffer.from(await fs.readFile('/etc/ssl/certs/ca-certificates.crt'))
    } catch (err: any) {
        if (err.code !== 'ENOENT') {
            logger.warn('⚠️ Failed to load system CA bundle', { err })
        }
    }

    return {
        serverRootCACertificate: Buffer.concat([systemCAs, Buffer.from(TEMPORAL_CLIENT_ROOT_CA)]),
        clientCertPair: {
            crt: Buffer.from(TEMPORAL_CLIENT_CERT),
            key: Buffer.from(TEMPORAL_CLIENT_KEY),
        },
    }
}

/**
 * Encrypts payloads with the same key as the Python workers. A workflow started from Python and an
 * activity run here read each other's payloads, so both sides need the same codec or neither.
 */
export function buildTemporalDataConverter(config: TemporalConnectionConfig): DataConverter | undefined {
    if (!config.TEMPORAL_SECRET_KEY) {
        logger.warn('⚠️ No TEMPORAL_SECRET_KEY configured — workflow payloads will NOT be encrypted')
        return undefined
    }
    const fallbackKeys = config.TEMPORAL_FALLBACK_SECRET_KEYS.split(',')
        .map((key) => key.trim())
        .filter(Boolean)
    return { payloadCodecs: [new EncryptionCodec(config.TEMPORAL_SECRET_KEY, fallbackKeys)] }
}
