import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { logger } from '../../utils/logger'
import { ValidRetentionPeriods } from '../shared/constants'
import { createDeletionBlockMetadata } from '../shared/metadata/session-block-metadata'
import { SessionMetadataStore } from '../shared/metadata/session-metadata-store'
import { RecordingApiMetrics } from './metrics'
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
    | { ok: true; deletedAt: number }
    | { ok: false; error: 'cleanup_failed'; metadataError?: unknown; postgresError?: unknown }

export type BulkDeleteRecordingsResult = {
    deleted: string[]
    failed: { session_id: string; error: string }[]
}

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
        const startTime = performance.now()

        logger.debug('[RecordingService] getBlock request', {
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
                RecordingApiMetrics.observeGetBlock('not_found', (performance.now() - startTime) / 1000)
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

            RecordingApiMetrics.observeGetBlock('success', (performance.now() - startTime) / 1000)
            return { ok: true, data: decrypted }
        } catch (error) {
            if (error instanceof SessionKeyDeletedError) {
                logger.info('[RecordingService] Session key has been deleted', {
                    teamId,
                    sessionId,
                    deleted_at: error.deletedAt,
                })
                RecordingApiMetrics.observeGetBlock('deleted', (performance.now() - startTime) / 1000)
                return { ok: false, error: 'deleted', deletedAt: error.deletedAt }
            }

            RecordingApiMetrics.observeGetBlock('error', (performance.now() - startTime) / 1000)
            throw error
        }
    }

    async deleteRecording(sessionId: string, teamId: number): Promise<DeleteRecordingResult> {
        const startTime = performance.now()
        logger.debug('[RecordingService] deleteRecording request', { teamId, sessionId })

        const result = await this.keyStore.deleteKey(sessionId, teamId)
        logger.debug('[RecordingService] deleteKey result', { teamId, sessionId, result })

        if (result.deleted) {
            const deletedAt = result.deletedAt
            const [metadataResult, postgresResult] = await Promise.allSettled([
                this.emitDeletionEvent(sessionId, teamId),
                this.deletePostgresRecords(sessionId, teamId),
            ])
            const metadataError = metadataResult.status === 'rejected' ? metadataResult.reason : undefined
            const postgresError = postgresResult.status === 'rejected' ? postgresResult.reason : undefined
            if (metadataError || postgresError) {
                logger.error('[RecordingService] Post-deletion cleanup failed', {
                    sessionId,
                    teamId,
                    metadataError: metadataError ?? null,
                    postgresError: postgresError ?? null,
                })
                RecordingApiMetrics.observeDeleteRecording('cleanup_failed', (performance.now() - startTime) / 1000)
                return { ok: false, error: 'cleanup_failed', metadataError, postgresError }
            }
            RecordingApiMetrics.observeDeleteRecording('success', (performance.now() - startTime) / 1000)
            return { ok: true, deletedAt }
        }

        // already_deleted
        logger.info('[RecordingService] Recording already deleted', {
            teamId,
            sessionId,
            deleted_at: result.deletedAt,
        })
        RecordingApiMetrics.observeDeleteRecording('success', (performance.now() - startTime) / 1000)
        return { ok: true, deletedAt: result.deletedAt }
    }

    async bulkDeleteRecordings(sessionIds: string[], teamId: number): Promise<BulkDeleteRecordingsResult> {
        logger.debug('[RecordingService] bulkDeleteRecordings request', { teamId, count: sessionIds.length })

        const results = await Promise.allSettled(sessionIds.map((sid) => this.deleteRecording(sid, teamId)))

        const deleted: string[] = []
        const failed: { session_id: string; error: string }[] = []

        for (let i = 0; i < results.length; i++) {
            const result = results[i]
            const sessionId = sessionIds[i]
            if (result.status === 'fulfilled') {
                if (result.value.ok) {
                    deleted.push(sessionId)
                } else {
                    failed.push({ session_id: sessionId, error: result.value.error })
                }
            } else {
                failed.push({ session_id: sessionId, error: 'unexpected_error' })
            }
        }

        logger.info('[RecordingService] bulkDeleteRecordings complete', {
            teamId,
            deletedCount: deleted.length,
            failedCount: failed.length,
        })

        return { deleted, failed }
    }

    private async emitDeletionEvent(sessionId: string, teamId: number): Promise<void> {
        if (!this.metadataStore) {
            logger.warn('[RecordingService] No metadata store configured, skipping deletion event', {
                sessionId,
                teamId,
            })
            return
        }

        await this.metadataStore.storeSessionBlocks([createDeletionBlockMetadata(sessionId, teamId)])

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

        const tables = ['ee_single_session_summary', 'posthog_exportedrecording', 'posthog_comment'] as const
        const results = await Promise.allSettled([
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM ee_single_session_summary WHERE team_id = $1 AND session_id = $2`,
                [teamId, sessionId],
                'deleteSessionSummary'
            ),
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_exportedrecording WHERE team_id = $1 AND session_id = $2`,
                [teamId, sessionId],
                'deleteExportedRecording'
            ),
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_comment WHERE team_id = $1 AND scope = 'recording' AND item_id = $2`,
                [teamId, sessionId],
                'deleteRecordingComments'
            ),
        ])

        const failures: string[] = []
        for (const [i, result] of results.entries()) {
            if (result.status === 'rejected') {
                failures.push(tables[i])
                logger.error('[RecordingService] Postgres deletion failed', {
                    sessionId,
                    teamId,
                    table: tables[i],
                    error: result.reason,
                })
            }
        }

        if (failures.length > 0) {
            throw new Error(`Failed to delete from: ${failures.join(', ')}`)
        }

        logger.info('[RecordingService] PostgreSQL records deleted', { sessionId, teamId })
    }
}
