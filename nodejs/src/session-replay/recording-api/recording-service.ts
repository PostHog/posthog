import { GetObjectCommand, NoSuchKey, S3Client } from '@aws-sdk/client-s3'

import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { logger, serializeError } from '../../utils/logger'
import { ValidRetentionPeriods } from '../shared/constants'
import { createDeletionBlockMetadata } from '../shared/metadata/session-block-metadata'
import { SessionMetadataStore } from '../shared/metadata/session-metadata-store'
import { RecordingApiMetrics } from './metrics'
import { DeleteKeyResult, KeyStore, RecordingDecryptor, SessionKeyDeletedError } from './types'

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
    | { sessionId: string; ok: true; status: 'deleted'; deletedAt: number }
    | { sessionId: string; ok: true; status: 'already_deleted'; deletedAt: number }
    | { sessionId: string; ok: false; error: 'shred_failed' }
    | { sessionId: string; ok: false; error: 'cleanup_failed'; deletedAt: number }

export type BulkDeleteRecordingsResult = DeleteRecordingResult[]

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
                RecordingApiMetrics.observeGetBlock('not_found', (performance.now() - startTime) / 1000, 'unknown')
                return { ok: false, error: 'not_found' }
            }

            const bodyContents = await response.Body.transformToByteArray()
            logger.debug('[RecordingService] S3 returned data', {
                key,
                bytesReceived: bodyContents.length,
            })

            const { data, sessionState } = await this.decryptor.decryptBlock(
                sessionId,
                teamId,
                Buffer.from(bodyContents)
            )

            logger.debug('[RecordingService] Decrypted block', {
                sessionId,
                teamId,
                inputSize: bodyContents.length,
                outputSize: data.length,
                sessionState,
            })

            RecordingApiMetrics.observeGetBlock('success', (performance.now() - startTime) / 1000, sessionState)
            return { ok: true, data }
        } catch (error) {
            if (error instanceof NoSuchKey) {
                logger.warn('[RecordingService] S3 object not found (NoSuchKey)', {
                    key,
                    teamId,
                    sessionId,
                })
                RecordingApiMetrics.observeGetBlock('not_found', (performance.now() - startTime) / 1000, 'unknown')
                return { ok: false, error: 'not_found' }
            }

            if (error instanceof SessionKeyDeletedError) {
                logger.info('[RecordingService] Session key has been deleted', {
                    teamId,
                    sessionId,
                    deleted_at: error.deletedAt,
                })
                RecordingApiMetrics.observeGetBlock('deleted', (performance.now() - startTime) / 1000, 'unknown')
                return { ok: false, error: 'deleted', deletedAt: error.deletedAt }
            }

            RecordingApiMetrics.observeGetBlock('error', (performance.now() - startTime) / 1000, 'unknown')
            throw error
        }
    }

    async deleteSingleRecording(sessionId: string, teamId: number): Promise<DeleteRecordingResult> {
        const startTime = performance.now()
        logger.debug('[RecordingService] deleteSingleRecording request', { teamId, sessionId })

        const result = await this.deleteRecording(sessionId, teamId, (sid, tid) => this.deletePostgresRecords(sid, tid))

        const metric = result.ok ? 'success' : result.error
        RecordingApiMetrics.observeDeleteRecording(metric, (performance.now() - startTime) / 1000)
        return result
    }

    async bulkDeleteRecordings(sessionIds: string[], teamId: number): Promise<BulkDeleteRecordingsResult> {
        const startTime = performance.now()
        logger.debug('[RecordingService] bulkDeleteRecordings request', { teamId, count: sessionIds.length })

        const pendingPostgres: string[] = []
        const results = await Promise.all(
            sessionIds.map((sid) =>
                this.deleteRecording(sid, teamId, (sessionId) => {
                    pendingPostgres.push(sessionId)
                    return Promise.resolve()
                })
            )
        )

        try {
            await this.bulkDeletePostgresRecords(pendingPostgres, teamId)
        } catch (error) {
            logger.error('[RecordingService] Bulk postgres deletion failed', {
                teamId,
                error: serializeError(error),
            })
            for (let i = 0; i < results.length; i++) {
                const r = results[i]
                if (r.ok && r.status === 'deleted') {
                    results[i] = { sessionId: r.sessionId, ok: false, error: 'cleanup_failed', deletedAt: r.deletedAt }
                }
            }
        }

        const deletedCount = results.filter((r) => r.ok).length
        const failedCount = sessionIds.length - deletedCount
        RecordingApiMetrics.observeBulkDeleteRecordings(
            failedCount > 0 ? 'partial' : 'success',
            (performance.now() - startTime) / 1000
        )
        logger.info('[RecordingService] bulkDeleteRecordings complete', {
            teamId,
            deletedCount,
            failedCount,
        })

        return results
    }

    private async deleteRecording(
        sessionId: string,
        teamId: number,
        deleteFromPostgres: (sessionId: string, teamId: number) => Promise<void>
    ): Promise<DeleteRecordingResult> {
        let shredResult: DeleteKeyResult
        try {
            shredResult = await this.shredKey(sessionId, teamId)
        } catch {
            return { sessionId, ok: false, error: 'shred_failed' }
        }

        if (!shredResult.deleted) {
            return { sessionId, ok: true, status: 'already_deleted', deletedAt: shredResult.deletedAt }
        }

        const [kafkaResult, postgresResult] = await Promise.allSettled([
            this.emitDeletionEvent(sessionId, teamId),
            deleteFromPostgres(sessionId, teamId),
        ])

        if (kafkaResult.status === 'rejected' || postgresResult.status === 'rejected') {
            return { sessionId, ok: false, error: 'cleanup_failed', deletedAt: shredResult.deletedAt }
        }

        return { sessionId, ok: true, status: 'deleted', deletedAt: shredResult.deletedAt }
    }

    private async shredKey(sessionId: string, teamId: number): Promise<DeleteKeyResult> {
        const result = await this.keyStore.deleteKey(sessionId, teamId)
        logger.debug('[RecordingService] shredKey result', { teamId, sessionId, result })
        return result
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
                    error: serializeError(result.reason),
                })
            }
        }

        if (failures.length > 0) {
            throw new Error(`Failed to delete from: ${failures.join(', ')}`)
        }

        logger.info('[RecordingService] PostgreSQL records deleted', { sessionId, teamId })
    }

    private async bulkDeletePostgresRecords(sessionIds: string[], teamId: number): Promise<void> {
        if (sessionIds.length === 0 || !this.postgres) {
            return
        }

        const tables = ['ee_single_session_summary', 'posthog_exportedrecording', 'posthog_comment'] as const
        const results = await Promise.allSettled([
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM ee_single_session_summary WHERE team_id = $1 AND session_id = ANY($2)`,
                [teamId, sessionIds],
                'bulkDeleteSessionSummaries'
            ),
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_exportedrecording WHERE team_id = $1 AND session_id = ANY($2)`,
                [teamId, sessionIds],
                'bulkDeleteExportedRecordings'
            ),
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_comment WHERE team_id = $1 AND scope = 'recording' AND item_id = ANY($2)`,
                [teamId, sessionIds],
                'bulkDeleteRecordingComments'
            ),
        ])

        const failures: string[] = []
        for (const [i, result] of results.entries()) {
            if (result.status === 'rejected') {
                failures.push(tables[i])
            }
        }

        if (failures.length > 0) {
            throw new Error(`Failed to delete from: ${failures.join(', ')}`)
        }

        logger.info('[RecordingService] Bulk PostgreSQL records deleted', { teamId, sessionCount: sessionIds.length })
    }
}
