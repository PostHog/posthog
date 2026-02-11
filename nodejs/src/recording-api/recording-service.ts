import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { ValidRetentionPeriods } from '../session-recording/constants'
import { createNoopBlockMetadata } from '../session-recording/sessions/session-block-metadata'
import { SessionMetadataStore } from '../session-recording/sessions/session-metadata-store'
import { PostgresRouter, PostgresUse } from '../utils/db/postgres'
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
    | { ok: false; error: 'not_supported' }

export class RecordingService {
    constructor(
        private s3Client: S3Client,
        private s3Bucket: string,
        private s3Prefix: string,
        private keyStore: KeyStore,
        private decryptor: RecordingDecryptor,
        private metadataStore?: SessionMetadataStore,
        private postgres?: PostgresRouter
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

        const result = await this.keyStore.deleteKey(sessionId, teamId)
        logger.debug('[RecordingService] deleteKey result', { teamId, sessionId, result })

        if (result.deleted) {
            try {
                await this.emitDeletionEvent(sessionId, teamId)
                await this.deletePostgresRecords(sessionId, teamId)
            } catch (error) {
                logger.error('[RecordingService] Post-deletion cleanup failed', { sessionId, teamId, error })
            }
            return { ok: true }
        }

        if (result.reason === 'already_deleted') {
            logger.info('[RecordingService] Recording already deleted', {
                teamId,
                sessionId,
                deleted_at: result.deletedAt,
            })
            return { ok: false, error: 'already_deleted', deletedAt: result.deletedAt }
        }

        if (result.reason === 'not_supported') {
            return { ok: false, error: 'not_supported' }
        }

        return { ok: false, error: 'not_found' }
    }

    private async emitDeletionEvent(sessionId: string, teamId: number): Promise<void> {
        if (!this.metadataStore) {
            logger.warn('[RecordingService] No metadata store configured, skipping deletion event', {
                sessionId,
                teamId,
            })
            return
        }

        const deletionMetadata = { ...createNoopBlockMetadata(sessionId, teamId), isDeleted: true }
        await this.metadataStore.storeSessionBlocks([deletionMetadata])

        logger.info('[RecordingService] Deletion event emitted', { sessionId, teamId })
    }

    private async deletePostgresRecords(sessionId: string, teamId: number): Promise<void> {
        if (!this.postgres) {
            logger.warn('[RecordingService] No postgres configured, skipping record deletion', {
                sessionId,
                teamId,
            })
            return
        }

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM ee_single_session_summary WHERE team_id = $1 AND session_id = $2`,
            [teamId, sessionId],
            'deleteSessionSummary'
        )

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM posthog_exportedrecording WHERE team_id = $1 AND session_id = $2`,
            [teamId, sessionId],
            'deleteExportedRecording'
        )

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM posthog_comment WHERE team_id = $1 AND scope = 'recording' AND item_id = $2`,
            [teamId, sessionId],
            'deleteRecordingComments'
        )

        // CASCADE deletes: SessionRecordingViewed, SessionRecordingExternalReference, SessionRecordingPlaylistItem
        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM posthog_sessionrecording WHERE team_id = $1 AND session_id = $2`,
            [teamId, sessionId],
            'deleteSessionRecording'
        )

        logger.info('[RecordingService] PostgreSQL records deleted', { sessionId, teamId })
    }
}
