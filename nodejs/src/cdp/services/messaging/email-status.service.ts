import { Counter } from 'prom-client'
import { setTimeout as delay } from 'timers/promises'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'

import { EMAIL_STATUS_OUTPUT, EmailStatusOutput } from '../../outputs/outputs'
import { CyclotronJobInvocationHogFunction } from '../../types'
import { TRANSACTIONAL_EMAIL_EVENT } from '../hogflows/hogflow-sensitivity'

const counterEmailStatusRowsProduced = new Counter({
    name: 'cdp_email_status_rows_produced',
    help: 'Transactional email status rows produced to the email_status Kafka topic.',
    labelNames: ['status'],
})

const counterEmailStatusWriteFailed = new Counter({
    name: 'cdp_email_status_write_failed',
    help: 'Transactional email status rows dropped because they could not be built or produced. The send is never affected.',
    labelNames: ['status'],
})

export type EmailStatus = 'queued' | 'failed' | 'sent' | 'delivered' | 'bounced' | 'complained'

export type EmailStatusReason =
    // A failed send. The provider rejected the email, or the send could not be made.
    'provider_error'

// The rank is the high part of `version`, so a message's status only moves forward in the
// ReplacingMergeTree, whatever order the rows arrive in. `failed` ranks below `sent` so that a
// successful rerun of the same invocation replaces the failed attempt.
const STATUS_RANK: Record<EmailStatus, bigint> = {
    queued: 0n,
    failed: 1n,
    sent: 2n,
    delivered: 3n,
    bounced: 4n,
    complained: 5n,
}

// 2^48 ms is past the year 10000, so the status time never reaches into the rank bits.
const STATUS_AT_BITS = 48n

// How long a request path waits for its status rows. See `flushWithin`.
export const EMAIL_STATUS_FLUSH_MAX_WAIT_MS = 1000

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export interface EmailStatusRow {
    team_id: number
    message_id: string
    status: EmailStatus
    // A decimal string, because the value is past Number.MAX_SAFE_INTEGER. ClickHouse parses it as UInt64.
    version: string
    created_at: string
    status_at: string
    reason: string
}

export interface EmailStatusUpdate {
    teamId: number
    // The hog flow invocation id, which the transactional email API returns as `message_id`.
    messageId: string
    status: EmailStatus
    reason?: EmailStatusReason
    // When the status changed. Defaults to now.
    statusAt?: Date
}

const isoMicroseconds = (date: Date): string => {
    // ClickHouse DateTime64(6) accepts 'YYYY-MM-DD HH:MM:SS.ffffff'.
    return date.toISOString().replace('T', ' ').replace('Z', '000')
}

// A UUIDT starts with its creation time as 48 bits of Unix milliseconds.
const uuidtCreatedAt = (messageId: string): Date => {
    if (!UUID_REGEX.test(messageId)) {
        throw new Error('message id is not a UUID')
    }
    return new Date(parseInt(messageId.slice(0, 8) + messageId.slice(9, 13), 16))
}

export const buildEmailStatusRow = (update: EmailStatusUpdate): EmailStatusRow => {
    const statusAt = update.statusAt && !Number.isNaN(update.statusAt.getTime()) ? update.statusAt : new Date()
    const version = (STATUS_RANK[update.status] << STATUS_AT_BITS) + BigInt(statusAt.getTime())
    return {
        team_id: update.teamId,
        message_id: update.messageId,
        status: update.status,
        version: version.toString(),
        // Derived from the message id rather than the clock, so every row of a message lands in
        // the same `toYYYYMMDD(created_at)` partition and the rows can collapse.
        created_at: isoMicroseconds(uuidtCreatedAt(update.messageId)),
        status_at: isoMicroseconds(statusAt),
        reason: update.reason ?? '',
    }
}

// A transactional email run is triggered by the synthetic event that the transactional email API creates.
export const isTransactionalEmailSend = (invocation: CyclotronJobInvocationHogFunction): boolean =>
    invocation.state?.globals?.event?.event === TRANSACTIONAL_EMAIL_EVENT

/**
 * Records each status change of a transactional email for the email_status ClickHouse table.
 *
 * Rows are buffered by `queue` and produced by `flush`. Both are best-effort and never throw:
 * a status row that cannot be written is logged and counted, and the send it describes goes on.
 */
export class EmailStatusService {
    private queuedRows: EmailStatusRow[] = []

    constructor(
        private outputs: IngestionOutputs<EmailStatusOutput>,
        private config: { EMAIL_STATUS_ENABLED: boolean }
    ) {}

    queue(update: EmailStatusUpdate): void {
        if (!this.config.EMAIL_STATUS_ENABLED) {
            return
        }
        try {
            this.queuedRows.push(buildEmailStatusRow(update))
        } catch (error) {
            counterEmailStatusWriteFailed.inc({ status: update.status })
            logger.error('⚠️', 'failed to build an email status row', {
                error: String(error),
                team_id: update.teamId,
                message_id: update.messageId,
                status: update.status,
            })
        }
    }

    // Required by ResultSink. The rows go through the shared Kafka outputs, which the server
    // disconnects separately on shutdown.
    async stop(): Promise<void> {
        return Promise.resolve()
    }

    // For request paths: the reply waits at most `maxWaitMs`, and rows still in flight are produced in the
    // background. The status API already documents that a status can arrive a few seconds late.
    async flushWithin(maxWaitMs: number): Promise<void> {
        const flushed = this.flush()
        await Promise.race([flushed, delay(maxWaitMs, undefined, { ref: false })])
    }

    async flush(): Promise<void> {
        if (this.queuedRows.length === 0) {
            return
        }
        const rows = this.queuedRows
        this.queuedRows = []

        await Promise.all(
            rows.map(async (row) => {
                try {
                    await this.outputs.produce(EMAIL_STATUS_OUTPUT, {
                        // Keyed by message so all rows of a message go to the same partition.
                        key: Buffer.from(row.message_id),
                        value: Buffer.from(JSON.stringify(row)),
                    })
                    counterEmailStatusRowsProduced.inc({ status: row.status })
                } catch (error) {
                    counterEmailStatusWriteFailed.inc({ status: row.status })
                    logger.error('⚠️', 'failed to produce an email status row', {
                        error: String(error),
                        team_id: row.team_id,
                        message_id: row.message_id,
                        status: row.status,
                    })
                }
            })
        )
    }
}
