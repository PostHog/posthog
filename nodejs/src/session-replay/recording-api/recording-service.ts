import { GetObjectCommand, NoSuchKey, S3Client } from '@aws-sdk/client-s3'

import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { logger, serializeError } from '../../utils/logger'
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
    | { ok: false; error: 'deleted'; deletedAt?: number; deletedBy: string }

export type DeleteRecordingResult =
    | { sessionId: string; ok: true; status: 'deleted'; deletedAt: number; deletedBy: string }
    | { sessionId: string; ok: true; status: 'already_deleted'; deletedAt: number; deletedBy: string }
    | { sessionId: string; ok: false; error: 'shred_failed' }
    | { sessionId: string; ok: false; error: 'cleanup_failed'; deletedAt: number; deletedBy: string }

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
                    deleted_by: error.deletedBy,
                })
                RecordingApiMetrics.observeGetBlock('deleted', (performance.now() - startTime) / 1000, 'unknown')
                return { ok: false, error: 'deleted', deletedAt: error.deletedAt, deletedBy: error.deletedBy }
            }

            RecordingApiMetrics.observeGetBlock('error', (performance.now() - startTime) / 1000, 'unknown')
            throw error
        }
    }

    async deleteRecordings(sessionIds: string[], teamId: number, deletedBy: string): Promise<DeleteRecordingResult[]> {
        const startTime = performance.now()
        logger.debug('[RecordingService] deleteRecordings request', { teamId, count: sessionIds.length, deletedBy })

        // Phase 1: Shred encryption keys — the irreversible step that makes recordings unreadable
        const shredResults = await Promise.all(
            sessionIds.map(async (sessionId) => ({
                sessionId,
                shredResult: await this.keyStore.deleteKey(sessionId, teamId, deletedBy).catch((): null => null),
            }))
        )

        const newlyDeletedIds = shredResults.filter((r) => r.shredResult?.deleted).map((r) => r.sessionId)

        // Phase 2: Best-effort cleanup for newly shredded sessions (kafka + postgres in parallel)
        let cleanupOk = true
        if (newlyDeletedIds.length > 0) {
            const [kafkaResult, postgresResult] = await Promise.allSettled([
                this.emitDeletionEvents(newlyDeletedIds, teamId),
                this.deletePostgresRecords(newlyDeletedIds, teamId),
            ])
            for (const result of [kafkaResult, postgresResult]) {
                if (result.status === 'rejected') {
                    cleanupOk = false
                    logger.error('[RecordingService] Cleanup step failed', {
                        teamId,
                        error: serializeError(result.reason),
                    })
                }
            }

            try {
                await this.logActivity(newlyDeletedIds, teamId, deletedBy)
            } catch (error) {
                cleanupOk = false
                logger.error('[RecordingService] Failed to log activity', { teamId, error: serializeError(error) })
            }
        }

        // Build results
        const results = shredResults.map(({ sessionId, shredResult }): DeleteRecordingResult => {
            if (!shredResult) {
                return { sessionId, ok: false, error: 'shred_failed' }
            }
            if (!shredResult.deleted) {
                return {
                    sessionId,
                    ok: true,
                    status: 'already_deleted',
                    deletedAt: shredResult.deletedAt,
                    deletedBy: shredResult.deletedBy,
                }
            }
            if (!cleanupOk) {
                return { sessionId, ok: false, error: 'cleanup_failed', deletedAt: shredResult.deletedAt, deletedBy }
            }
            return { sessionId, ok: true, status: 'deleted', deletedAt: shredResult.deletedAt, deletedBy }
        })

        const deletedCount = results.filter((r) => r.ok).length
        const failedCount = sessionIds.length - deletedCount
        RecordingApiMetrics.observeDeleteRecordings(
            failedCount > 0 ? 'partial' : 'success',
            (performance.now() - startTime) / 1000
        )
        logger.info('[RecordingService] deleteRecordings complete', { teamId, deletedCount, failedCount })

        return results
    }

    private async emitDeletionEvents(sessionIds: string[], teamId: number): Promise<void> {
        if (!this.metadataStore) {
            return
        }
        await this.metadataStore.storeSessionBlocks(
            sessionIds.map((sessionId) => createDeletionBlockMetadata(sessionId, teamId))
        )
    }

    private async deletePostgresRecords(sessionIds: string[], teamId: number): Promise<void> {
        if (sessionIds.length === 0 || !this.postgres) {
            return
        }

        const tables = ['ee_single_session_summary', 'posthog_exportedrecording', 'posthog_comment'] as const
        const results = await Promise.allSettled([
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM ee_single_session_summary WHERE team_id = $1 AND session_id = ANY($2)`,
                [teamId, sessionIds],
                'deleteSessionSummaries'
            ),
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_exportedrecording WHERE team_id = $1 AND session_id = ANY($2)`,
                [teamId, sessionIds],
                'deleteExportedRecordings'
            ),
            this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_comment WHERE team_id = $1 AND scope = 'recording' AND item_id = ANY($2)`,
                [teamId, sessionIds],
                'deleteRecordingComments'
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

        logger.info('[RecordingService] PostgreSQL records deleted', { teamId, sessionCount: sessionIds.length })
    }

    private async logActivity(sessionIds: string[], teamId: number, deletedBy: string): Promise<void> {
        if (sessionIds.length === 0 || !this.postgres) {
            return
        }

        const detail = JSON.stringify({ type: 'recording_shredded', deleted_by: deletedBy })
        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_activitylog (id, team_id, is_system, activity, item_id, scope, detail, created_at)
             SELECT gen_random_uuid(), $1, true, 'deleted', unnest($2::text[]), 'Replay', $3::jsonb, now()`,
            [teamId, sessionIds, detail],
            'logRecordingDeletion'
        )
    }
}
