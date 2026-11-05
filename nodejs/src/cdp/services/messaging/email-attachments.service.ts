import { createHash } from 'crypto'
import { Counter, Histogram } from 'prom-client'

import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { LazyPool } from '~/cdp/utils/lazy-pool'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import type { DecodedAttachment } from '../hogflows/transactional-email'

export const EMAIL_ATTACHMENTS_MAX_CONNECTIONS = 5

export type EmailAttachmentOutcome = 'stored' | 'loaded' | 'missing' | 'deleted' | 'swept'

export const emailAttachmentOutcomesTotal = new Counter({
    name: 'cdp_email_attachment_outcomes_total',
    help: 'Transactional email attachment files by outcome: stored by the API, loaded by the email worker, missing when the worker found no matching rows and failed the send, deleted after a terminal send outcome, and swept by the janitor because no send outcome deleted them.',
    labelNames: ['outcome'],
})

export const emailAttachmentBytesPerSend = new Histogram({
    name: 'cdp_email_attachment_bytes_per_send',
    help: 'Total decoded bytes of the attachment files of one transactional email, observed when the API stores them.',
    buckets: [1_024, 8_192, 32_768, 65_536, 131_072, 262_144, 393_216, 524_288],
})

export const EMAIL_ATTACHMENTS_MISSING = 'attachments_missing'

export class EmailAttachmentsMissingError extends Error {
    constructor() {
        super(
            `${EMAIL_ATTACHMENTS_MISSING}: the attachment files of this email are no longer stored, so it was not sent without them.`
        )
    }
}

type AttachmentRow = {
    position: number
    filename: string
    content_type: string | null
    content_id: string | null
    content: Buffer
    sha256: string
}

export class EmailAttachmentsService {
    private readonly pool: LazyPool

    constructor(databaseUrl: string | undefined, maxConnections?: number) {
        this.pool = new LazyPool(databaseUrl, maxConnections, (err) => {
            logger.error('⚠️', 'Email attachments pool error', { error: err.message })
        })
    }

    public async store(jobId: string, teamId: number, files: DecodedAttachment[]): Promise<void> {
        const pool = this.pool.get()
        if (!pool) {
            throw new Error('Email attachments need CYCLOTRON_NODE_DATABASE_URL')
        }
        const values: unknown[] = []
        const placeholders = files.map((file, position) => {
            const offset = values.length
            values.push(
                jobId,
                teamId,
                position,
                file.filename,
                file.contentType ?? null,
                file.contentId ?? null,
                file.content,
                file.sizeBytes,
                file.sha256
            )
            return `(gen_random_uuid(), ${Array.from({ length: 9 }, (_, i) => `$${offset + i + 1}`).join(', ')})`
        })
        await pool.query(
            `INSERT INTO cyclotron_email_attachments
                (id, job_id, team_id, position, filename, content_type, content_id, content, size_bytes, sha256)
             VALUES ${placeholders.join(', ')}`,
            values
        )
        emailAttachmentOutcomesTotal.inc({ outcome: 'stored' }, files.length)
        emailAttachmentBytesPerSend.observe(files.reduce((total, file) => total + file.sizeBytes, 0))
    }

    public async load(
        jobId: string,
        teamId: number,
        expected: readonly EmailAttachmentMetadata[]
    ): Promise<DecodedAttachment[]> {
        const pool = this.pool.get()
        const rows = pool
            ? (
                  await pool.query<AttachmentRow>(
                      `SELECT position, filename, content_type, content_id, content, sha256
                       FROM cyclotron_email_attachments WHERE job_id = $1 AND team_id = $2 ORDER BY position`,
                      [jobId, teamId]
                  )
              ).rows
            : []
        const matches =
            rows.length === expected.length &&
            rows.every(
                (row, i) =>
                    row.position === i &&
                    row.sha256 === expected[i].sha256 &&
                    createHash('sha256').update(row.content).digest('hex') === expected[i].sha256
            )
        if (!matches) {
            emailAttachmentOutcomesTotal.inc({ outcome: 'missing' }, expected.length)
            logger.error('⚠️', 'Email attachment rows are missing or do not match the job', {
                job_id: jobId,
                expected: expected.length,
                found: rows.length,
            })
            throw new EmailAttachmentsMissingError()
        }
        emailAttachmentOutcomesTotal.inc({ outcome: 'loaded' }, rows.length)
        return rows.map((row, i) => ({ ...expected[i], content: row.content }))
    }

    public async delete(jobId: string, teamId: number): Promise<void> {
        try {
            const pool = this.pool.get()
            if (!pool) {
                return
            }
            const result = await pool.query(
                `DELETE FROM cyclotron_email_attachments
                 WHERE job_id = $1 AND team_id = $2
                   AND NOT EXISTS (
                       SELECT 1 FROM cyclotron_jobs WHERE id = $1 AND status IN ('available', 'running')
                   )`,
                [jobId, teamId]
            )
            emailAttachmentOutcomesTotal.inc({ outcome: 'deleted' }, result.rowCount ?? 0)
        } catch (err) {
            logger.warn('⚠️', 'Failed to delete email attachment rows', {
                job_id: jobId,
                error: err instanceof Error ? err.message : String(err),
            })
            captureException(err)
        }
    }

    public async stop(): Promise<void> {
        await this.pool.end()
    }
}
