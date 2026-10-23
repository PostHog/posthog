import { Counter } from 'prom-client'

import { EMAIL_STATUS_OUTPUT, EmailStatusOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'

import { TRANSACTIONAL_EMAIL_EVENT } from '../hogflows/hogflow-sensitivity'

const emailStatusRowsProduced = new Counter({
    name: 'cdp_email_status_rows_produced',
    help: 'Status rows produced for the email_status ClickHouse table.',
    labelNames: ['status'],
})

const emailStatusWriteFailed = new Counter({
    name: 'cdp_email_status_write_failed',
    help: 'Status rows that failed to produce to Kafka. The email itself is not affected.',
    labelNames: ['status'],
})

export const emailStatusMissingRecipientHash = new Counter({
    name: 'cdp_email_status_missing_recipient_hash',
    help: 'Transactional emails with no recipient hash, so no status row was written. Jobs queued before the hash existed, and sends while no salt key is configured, land here.',
    labelNames: ['source'],
})

// The rank is the high part of the row version, so a status only moves forward: a late `sent`
// never replaces `delivered`. A `failed` from SES ranks above `sent`, because SES can reject an email it accepted.
const STATUS_RANK = {
    queued: 0,
    unknown: 1,
    skipped: 2,
    sent: 3,
    failed: 4,
    delivered: 5,
    bounced: 6,
    complained: 7,
} as const

export type EmailStatus = keyof typeof STATUS_RANK

// A rerun keeps the message id, so its `skipped` or `sent` must replace the failed attempt it reruns.
// Such a failure ranks with `unknown`, another attempt outcome that the next attempt replaces.
const ATTEMPT_FAILURE_REASONS: ReadonlySet<string> = new Set(['provider_error', 'gave_up'])

const rankOf = (status: EmailStatus, reason: string | undefined): number =>
    status === 'failed' && reason !== undefined && ATTEMPT_FAILURE_REASONS.has(reason)
        ? STATUS_RANK.unknown
        : STATUS_RANK[status]

export type StatusChange = {
    teamId: number
    // The CDP invocation id the transactional email route returns. It is a UUIDT.
    messageId: string
    status: EmailStatus
    at: Date
    recipientHash: string
    reason?: string
}

export interface EmailStatusWriter {
    /** Resolves when Kafka confirms, and rejects when the produce fails. */
    record(change: StatusChange): Promise<void>
    /** Does not wait. Only cdp-api uses this, for `queued`. */
    recordInBackground(change: StatusChange): void
}

type EmailStatusRow = {
    team_id: number
    message_id: string
    status: EmailStatus
    version: number
    created_at: string
    status_at: string
    reason: string
    recipient_hash: string
}

const STATUS_TIME_BITS = 2 ** 48

const versionOf = (change: StatusChange): number =>
    rankOf(change.status, change.reason) * STATUS_TIME_BITS + change.at.getTime()

// A UUIDT carries its creation time in milliseconds in its first 48 bits. Every row of a message
// derives `created_at` from the message id, so the rows share a partition and replace each other.
const createdAtOf = (messageId: string): Date => new Date(parseInt(messageId.replace(/-/g, '').slice(0, 12), 16))

const clickhouseDateTime64 = (date: Date): string => date.toISOString().replace('T', ' ').replace('Z', '000')

export type EmailStatusSource = 'route' | 'worker' | 'janitor'

/**
 * The recipient hash to write status rows with, or undefined when the run is not a transactional
 * email. The transactional email route stamps its trigger event name and the hash on the run.
 */
export function transactionalEmailRecipientHash(
    run: { triggerEvent?: string; recipientHash?: string },
    source: EmailStatusSource
): string | undefined {
    if (run.triggerEvent !== TRANSACTIONAL_EMAIL_EVENT) {
        return undefined
    }
    if (!run.recipientHash) {
        emailStatusMissingRecipientHash.inc({ source })
        return undefined
    }
    return run.recipientHash
}

export async function recordSkippedTransactionalEmail(
    writer: EmailStatusWriter,
    run: { id: string; teamId: number; state?: { event?: { event?: string }; emailRecipientHash?: string } | null },
    reason: string
): Promise<void> {
    const recipientHash = transactionalEmailRecipientHash(
        { triggerEvent: run.state?.event?.event, recipientHash: run.state?.emailRecipientHash },
        'worker'
    )
    if (!recipientHash) {
        return
    }
    // The run already ended, so a failed status write must not fail it and run it again. record() counts and logs it.
    await writer
        .record({ teamId: run.teamId, messageId: run.id, status: 'skipped', at: new Date(), recipientHash, reason })
        .catch(() => undefined)
}

export class EmailStatusService implements EmailStatusWriter {
    constructor(private outputs: IngestionOutputs<EmailStatusOutput>) {}

    async record(change: StatusChange): Promise<void> {
        const row = this.rowFor(change)
        try {
            await this.outputs.produce(EMAIL_STATUS_OUTPUT, {
                key: Buffer.from(row.message_id),
                value: Buffer.from(JSON.stringify(row)),
            })
            emailStatusRowsProduced.inc({ status: row.status })
        } catch (error) {
            emailStatusWriteFailed.inc({ status: row.status })
            logger.error('Failed to record an email status', {
                status: row.status,
                message_id: row.message_id,
                error: String(error),
            })
            throw error
        }
    }

    recordInBackground(change: StatusChange): void {
        // record() already counts and logs the failure, and nothing waits on this write.
        void this.record(change).catch(() => undefined)
    }

    private rowFor(change: StatusChange): EmailStatusRow {
        return {
            team_id: change.teamId,
            message_id: change.messageId,
            status: change.status,
            version: versionOf(change),
            created_at: clickhouseDateTime64(createdAtOf(change.messageId)),
            status_at: clickhouseDateTime64(change.at),
            reason: change.reason ?? '',
            recipient_hash: change.recipientHash,
        }
    }
}
