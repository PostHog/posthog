import { Counter } from 'prom-client'
import { setTimeout as delay } from 'timers/promises'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'

import { EMAIL_STATUS_OUTPUT, EmailStatusOutput } from '../../outputs/outputs'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../../types'
import { TRANSACTIONAL_EMAIL_EVENT } from '../hogflows/hogflow-sensitivity'
import { classifyError } from '../monitoring/hog-invocation-results.service'

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
    // A bounce type, in the words the `$bounce_type` event property uses.
    | 'hard'
    | 'soft'
    | 'unknown'
    // A failed send. The provider rejected the email, or the send could not be made.
    | 'provider_error'
    // The provider refused the email after it accepted the send, for example because it found a virus.
    | 'provider_rejected'
    // A send that was skipped. The first four are also the codes the transactional email API
    // returns when it refuses a send before it queues the run.
    | EmailSkipReason
    // A run that was canceled before it finished.
    | 'canceled'
    // A run whose workflow or team no longer exists when it is dequeued.
    | 'workflow_unavailable'
    // A run that failed. The reason is the `error_kind` that hog_invocation_results stores for the
    // run, for example `hog_error` or `timeout`.
    | (string & {})

export type EmailSkipReason =
    | 'recipient_suppressed'
    | 'sending_paused'
    | 'sending_suspended'
    | 'recipient_unreachable'
    | 'missing_recipient'
    | 'recipient_opted_out'
    | 'frequency_capped'

// The rank is the high part of `version`, so a message's status only moves forward in the
// ReplacingMergeTree, whatever order the rows arrive in. `failed` ranks below `sent` so that a
// successful rerun of the same invocation replaces the failed attempt. The gaps let a failure take the
// rank between two statuses. Never renumber a rank, because rows already written keep their versions.
const STATUS_RANK: Record<EmailStatus, bigint> = {
    queued: 0n,
    failed: 2n,
    sent: 3n,
    delivered: 5n,
    bounced: 6n,
    complained: 7n,
}

// A run that fails on its email step fails after the step recorded why, for example
// `provider_error`. The run's own failure ranks lower, so it never replaces that reason.
const RUN_FAILED_RANK = 1n

// A provider rejection comes after the provider accepted the send, so it must replace `sent`. The
// provider never delivers a rejected email, so `delivered` and later statuses still rank above it.
const PROVIDER_REJECTED_RANK = 4n

// 2^48 ms is past the year 10000, so the status time never reaches into the rank bits.
const STATUS_AT_BITS = 48n

// How long a flush waits for its rows. See `flush`.
const EMAIL_STATUS_FLUSH_MAX_WAIT_MS = 1000

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
    // A failure of the whole run rather than of the email step.
    runOutcome?: boolean
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
    const rank =
        update.status !== 'failed'
            ? STATUS_RANK[update.status]
            : update.runOutcome
              ? RUN_FAILED_RANK
              : update.reason === 'provider_rejected'
                ? PROVIDER_REJECTED_RANK
                : STATUS_RANK.failed
    const version = (rank << STATUS_AT_BITS) + BigInt(statusAt.getTime())
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

const isTransactionalEmailRun = (invocation: CyclotronJobInvocation): boolean =>
    'hogFlow' in invocation && invocation.state?.event?.event === TRANSACTIONAL_EMAIL_EVENT

// A dequeued job has no `hogFlow` yet, so only its state says which event triggered it.
const isTransactionalEmailJob = (job: CyclotronJobInvocation): boolean =>
    (job.state as { event?: { event?: string } } | null)?.event?.event === TRANSACTIONAL_EMAIL_EVENT

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
        private config: { EMAIL_STATUS_ENABLED: boolean },
        private maxFlushWaitMs = EMAIL_STATUS_FLUSH_MAX_WAIT_MS
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

    // A skipped send has no later status, so it is recorded as failed. Otherwise the message stays
    // queued, and the caller never learns that the email did not go out.
    queueSkippedSend(invocation: CyclotronJobInvocationHogFunction, reason: EmailSkipReason, isTest: boolean): void {
        if (isTest || !isTransactionalEmailSend(invocation)) {
            return
        }
        this.queue({ teamId: invocation.teamId, messageId: invocation.id, status: 'failed', reason })
    }

    // A run that fails or is canceled before its email step never reaches the email service, so the
    // run's outcome is the email's. A failed row is written even when the email went out or failed
    // earlier in the run, because a run failure ranks below both and so never replaces them.
    queueInvocationResults(results: CyclotronJobInvocationResult[]): void {
        for (const result of results) {
            if (!(result.error || result.canceled) || !isTransactionalEmailRun(result.invocation)) {
                continue
            }
            this.queue({
                teamId: result.invocation.teamId,
                messageId: result.invocation.id,
                status: 'failed',
                // Same precedence as the lifecycle row in hog_invocation_results: an error wins over a cancel.
                reason: result.error ? classifyError(result.error).kind : 'canceled',
                runOutcome: true,
            })
        }
    }

    // A job whose workflow or team is gone is dropped without a result, so nothing else records it.
    queueUnavailableRun(job: CyclotronJobInvocation): void {
        if (!isTransactionalEmailJob(job)) {
            return
        }
        this.queue({
            teamId: job.teamId,
            messageId: job.id,
            status: 'failed',
            reason: 'workflow_unavailable',
            runOutcome: true,
        })
    }

    // Required by ResultSink. The rows go through the shared Kafka outputs, which the server
    // disconnects separately on shutdown.
    async stop(): Promise<void> {
        return Promise.resolve()
    }

    // The caller waits at most `maxFlushWaitMs`, and rows still in flight are produced in the background.
    // A stalled produce then cannot hold up the send API's reply, the SES webhook, or a worker batch past
    // its timeout. The status API already documents that a status can arrive a few seconds late.
    async flush(): Promise<void> {
        if (this.queuedRows.length === 0) {
            return
        }
        const rows = this.queuedRows
        this.queuedRows = []
        await Promise.race([this.produce(rows), delay(this.maxFlushWaitMs, undefined, { ref: false })])
    }

    private async produce(rows: EmailStatusRow[]): Promise<void> {
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
