import snappy from 'snappy'

import { parseJSON } from '../../../utils/json-parse'
import { logger } from '../../../utils/logger'
import { RecordingDecryptor, RecordingEncryptor, SessionKey } from '../types'
import { CryptoMetrics } from './metrics'

/**
 * Decorator that wraps an encryptor and a decryptor to verify encrypt→decrypt
 * round-trip integrity on a sampled percentage of blocks during ingestion.
 *
 * A failed check never throws — it logs at error level and increments a
 * Prometheus counter so we can alert on it.
 */
export class VerifyingEncryptor implements RecordingEncryptor {
    constructor(
        private encryptor: RecordingEncryptor,
        private decryptor: RecordingDecryptor,
        private checkRate: number = 0
    ) {}

    async start(): Promise<void> {
        await this.encryptor.start()
        await this.decryptor.start()
    }

    encryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<Buffer> {
        return this.encryptor.encryptBlock(sessionId, teamId, blockData)
    }

    encryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): Buffer {
        const encrypted = this.encryptor.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)

        if (sessionKey.sessionState === 'ciphertext' && this.checkRate > 0 && Math.random() < this.checkRate) {
            this.verifyIntegrity(sessionId, teamId, blockData, encrypted, sessionKey)
        }

        return encrypted
    }

    private verifyIntegrity(
        sessionId: string,
        teamId: number,
        originalBlock: Buffer,
        encryptedBlock: Buffer,
        sessionKey: SessionKey
    ): void {
        CryptoMetrics.incrementCryptoIntegrityChecks()

        try {
            const decrypted = this.decryptor.decryptBlockWithKey(sessionId, teamId, encryptedBlock, sessionKey)

            if (!Buffer.from(decrypted).equals(originalBlock)) {
                throw new Error('Decrypted block does not match original')
            }

            const decompressed = snappy.uncompressSync(decrypted)

            const lines = decompressed.toString('utf-8').trim().split('\n')
            for (const line of lines) {
                parseJSON(line)
            }
        } catch (error) {
            CryptoMetrics.incrementCryptoIntegrityFailures()
            logger.error('[VerifyingEncryptor] Crypto integrity check failed', {
                sessionId,
                teamId,
                originalSize: originalBlock.length,
                encryptedSize: encryptedBlock.length,
                error: String(error),
            })
        }
    }
}
