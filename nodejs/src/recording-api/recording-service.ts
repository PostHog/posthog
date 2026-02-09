import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { ValidRetentionPeriods } from '../session-recording/constants'
import { logger } from '../utils/logger'
import { KeyStore, RecordingDecryptor, SessionKeyDeletedError } from './types'

export interface GetBlockParams {
    sessionId: string
    teamId: number
    key: string
    startByte: number
    endByte: number
}

export type GetBlockResult =
    | { ok: true; data: Buffer }
    | { ok: false; error: 'not_found' }
    | { ok: false; error: 'deleted'; deletedAt?: number }

export type DeleteRecordingResult =
    | { ok: true }
    | { ok: false; error: 'not_found' }
    | { ok: false; error: 'already_deleted'; deletedAt?: number }

export class RecordingService {
    constructor(
        private s3Client: S3Client,
        private s3Bucket: string,
        private s3Prefix: string,
        private keyStore: KeyStore,
        private decryptor: RecordingDecryptor
    ) {}

    validateS3Key(key: string): boolean {
        const pattern = `^${this.s3Prefix}/(${ValidRetentionPeriods.join('|')})/\\d+-[0-9a-f]{16}$`
        return new RegExp(pattern).test(key)
    }

    formatS3KeyError(): string {
        return `Invalid key format: must match ${this.s3Prefix}/{${ValidRetentionPeriods.join(',')}}/{timestamp}-{hex}`
    }

    async getBlock(params: GetBlockParams): Promise<GetBlockResult> {
        const { sessionId, teamId, key, startByte, endByte } = params

        logger.info('[RecordingService] getBlock request', {
            teamId,
            sessionId,
            key,
            start: startByte,
            end: endByte,
        })

        try {
            const command = new GetObjectCommand({
                Bucket: this.s3Bucket,
                Key: key,
                Range: `bytes=${startByte}-${endByte}`,
            })

            logger.debug('[RecordingService] Fetching from S3', {
                bucket: this.s3Bucket,
                key,
                range: `bytes=${startByte}-${endByte}`,
            })

            const response = await this.s3Client.send(command)

            if (!response.Body) {
                logger.debug('[RecordingService] S3 returned no body', { key })
                return { ok: false, error: 'not_found' }
            }

            const bodyContents = await response.Body.transformToByteArray()
            logger.debug('[RecordingService] S3 returned data', {
                key,
                bytesReceived: bodyContents.length,
            })

            const decrypted = await this.decryptor.decryptBlock(sessionId, teamId, Buffer.from(bodyContents))

            logger.debug('[RecordingService] Decrypted block', {
                sessionId,
                teamId,
                inputSize: bodyContents.length,
                outputSize: decrypted.length,
            })

            return { ok: true, data: decrypted }
        } catch (error) {
            if (error instanceof SessionKeyDeletedError) {
                logger.info('[RecordingService] Session key has been deleted', {
                    teamId,
                    sessionId,
                    deleted_at: error.deletedAt,
                })
                return { ok: false, error: 'deleted', deletedAt: error.deletedAt }
            }

            throw error
        }
    }

    async deleteRecording(sessionId: string, teamId: number): Promise<DeleteRecordingResult> {
        logger.info('[RecordingService] deleteRecording request', { teamId, sessionId })

        try {
            const deleted = await this.keyStore.deleteKey(sessionId, teamId)
            logger.debug('[RecordingService] deleteKey result', { teamId, sessionId, deleted })

            if (deleted) {
                return { ok: true }
            }
            return { ok: false, error: 'not_found' }
        } catch (error) {
            if (error instanceof SessionKeyDeletedError) {
                logger.info('[RecordingService] Recording already deleted', {
                    teamId,
                    sessionId,
                    deleted_at: error.deletedAt,
                })
                return { ok: false, error: 'already_deleted', deletedAt: error.deletedAt }
            }

            throw error
        }
    }
}
