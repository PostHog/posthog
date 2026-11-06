import { createHash } from 'crypto'
import { Counter, Histogram } from 'prom-client'

import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { LazyPool } from '~/cdp/utils/lazy-pool'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import {
    type DecodedAttachment,
    MAX_EMAIL_ATTACHMENTS_BYTES,
    MAX_EMAIL_ATTACHMENTS_BYTES_IN_POSTGRES,
} from '../hogflows/transactional-email'
import type { EmailAttachmentObjectStore } from './email-attachments-object-store'

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
    buckets: [1_024, 8_192, 65_536, 262_144, 524_288, 1_048_576, 2_621_440, 5_242_880, 10_485_760],
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
    content: Buffer | null
    storage_key: string | null
    sha256: string
}

const STORAGE_KEY_PREFIX = 'email-attachments'

const storageKey = (teamId: number, jobId: string, position: number): string =>
    `${STORAGE_KEY_PREFIX}/${teamId}/${jobId}/${position}`

export class EmailAttachmentsService {
    private readonly pool: LazyPool

    constructor(
        databaseUrl: string | undefined,
        maxConnections?: number,
        private readonly objectStore: EmailAttachmentObjectStore | null = null
    ) {
        this.pool = new LazyPool(databaseUrl, maxConnections, (err) => {
            logger.error('⚠️', 'Email attachments pool error', { error: err.message })
        })
    }

    public get maxTotalBytes(): number {
        return this.objectStore ? MAX_EMAIL_ATTACHMENTS_BYTES : MAX_EMAIL_ATTACHMENTS_BYTES_IN_POSTGRES
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
                this.objectStore ? null : file.content,
                this.objectStore ? storageKey(teamId, jobId, position) : null,
                file.sizeBytes,
                file.sha256
            )
            return `(gen_random_uuid(), ${Array.from({ length: 10 }, (_, i) => `$${offset + i + 1}`).join(', ')})`
        })
        // The rows go first, so that the janitor knows about every object even when an upload fails halfway.
        await pool.query(
            `INSERT INTO cyclotron_email_attachments
                (id, job_id, team_id, position, filename, content_type, content_id, content, storage_key, size_bytes, sha256)
             VALUES ${placeholders.join(', ')}`,
            values
        )
        const objectStore = this.objectStore
        if (objectStore) {
            await Promise.all(
                files.map((file, position) => objectStore.put(storageKey(teamId, jobId, position), file.content))
            )
        }
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
                      `SELECT position, filename, content_type, content_id, content, storage_key, sha256
                       FROM cyclotron_email_attachments WHERE job_id = $1 AND team_id = $2 ORDER BY position`,
                      [jobId, teamId]
                  )
              ).rows
            : []
        const contents = await Promise.all(rows.map((row) => this.contentOf(row)))
        const matches =
            rows.length === expected.length &&
            rows.every((row, i) => {
                const content = contents[i]
                return (
                    row.position === i &&
                    row.sha256 === expected[i].sha256 &&
                    content !== null &&
                    createHash('sha256').update(content).digest('hex') === expected[i].sha256
                )
            })
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
        return rows.map((_row, i) => ({ ...expected[i], content: contents[i]! }))
    }

    private async contentOf(row: AttachmentRow): Promise<Buffer | null> {
        if (!row.storage_key) {
            return row.content
        }
        if (!this.objectStore) {
            throw new Error('Email attachments are in object storage, but no bucket is configured')
        }
        return await this.objectStore.get(row.storage_key)
    }

    public async delete(jobId: string, teamId: number): Promise<void> {
        try {
            const pool = this.pool.get()
            if (!pool) {
                return
            }
            const stillQueued = `EXISTS (SELECT 1 FROM cyclotron_jobs WHERE id = $1 AND status IN ('available', 'running'))`
            if (this.objectStore) {
                // Objects go first: if this fails, the rows stay and the janitor finds the objects again.
                const stored = await pool.query<{ storage_key: string }>(
                    `SELECT storage_key FROM cyclotron_email_attachments
                     WHERE job_id = $1 AND team_id = $2 AND storage_key IS NOT NULL AND NOT ${stillQueued}`,
                    [jobId, teamId]
                )
                await this.objectStore.delete(stored.rows.map((row) => row.storage_key))
            }
            const result = await pool.query(
                `DELETE FROM cyclotron_email_attachments WHERE job_id = $1 AND team_id = $2 AND NOT ${stillQueued}`,
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
