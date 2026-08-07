import { Counter, Gauge } from 'prom-client'

import {
    CyclotronInvocationQueueParametersEmailType,
    CyclotronInvocationQueueParametersSendPushNotificationType,
    PushNotificationPayloadType,
} from '~/cdp/schema/cyclotron'
import { MESSAGE_ASSETS_OUTPUT, MessageAssetsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { safeClickhouseString } from '~/common/utils/db/utils'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, MessageAssetRow } from '../../types'
import { resolveEmailEngagementDistinctId } from './email-tracking.service'

export type { MessageAssetRow } from '../../types'

const counterMessageAssetsCaptured = new Counter({
    name: 'cdp_message_assets_captured',
    help: 'Sent-email assets produced to the message_assets Kafka topic (ClickHouse-backed).',
    labelNames: ['kind'],
})

const counterMessageAssetsFailed = new Counter({
    name: 'cdp_message_assets_failed',
    help: 'Asset captures that failed at Kafka produce and were dropped. Best-effort like logs/metrics — watch this counter to size the gap between sends and Assets-tab rows.',
})

const counterMessageAssetsTruncated = new Counter({
    name: 'cdp_message_assets_truncated',
    help: 'Sent-email assets whose rendered body exceeded the Kafka message-size budget. A placeholder is captured so the "View email" chip still works, but the original body is not viewable.',
})

const messageAssetsPendingRows = new Gauge({
    name: 'cdp_message_assets_pending_rows',
    help: 'Message-asset rows queued in-memory waiting for the next flush. Resets to 0 after each flush.',
})

const microsecondsSinceEpoch = (): string => {
    const ms = BigInt(Date.now())
    const subMs = BigInt(Math.floor((performance.now() % 1) * 1000))
    return (ms * 1000n + subMs).toString()
}

const isoMicroseconds = (date: Date): string => {
    // ClickHouse DateTime64(6) accepts 'YYYY-MM-DD HH:MM:SS.ffffff'.
    return date.toISOString().replace('T', ' ').replace('Z', '000')
}

const HTML_ESCAPE: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
}

// Escape user-typed `<`/`>`/`&` so a `<pre>`-wrapped plain-text body can't break
// surrounding markup or inject scripts.
const wrapPlainTextAsHtml = (text: string): string => {
    const escaped = text.replace(/[&<>"']/g, (c) => HTML_ESCAPE[c])
    return `<!doctype html><meta charset="utf-8"><pre style="white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace;margin:0;padding:1rem">${escaped}</pre>`
}

// The CDP Kafka producer caps message size at 6 MB in prod (1 MB elsewhere) but SES accepts
// up to 10 MB. In the gap the send succeeds and the log-line token is already emitted, so an
// oversized row that dropped at flush time would make the "View email" chip 404. Worse: since
// flush is a single Promise.all, one oversized row blows up the entire batch and every
// unrelated row in it gets swallowed too. Substitute a small placeholder body when we cross
// the safe budget — the row still lands, the chip works, and the batch is unaffected.
const MAX_HTML_BYTES = 4 * 1024 * 1024

const escapeHtml = (text: string): string => text.replace(/[&<>"']/g, (c) => HTML_ESCAPE[c])

// A push has no stored body to replay the way an email does, so render the delivered content into the
// same `html` column. That keeps one asset pipeline and one viewer for both channels: the person view
// renders this snapshot instead of needing a push-specific renderer.
// Only the parts the recipient actually saw are rendered. The custom `data` payload is deliberately
// left out: it is app routing context, not user-visible, and can carry arbitrary customer data we
// should not be re-displaying in the UI.
//
// Two interpolations below carry a `nosemgrep` for `raw-html-format`. That rule fires on customer data
// reaching a hand-built HTML string at all and can't see a local escaper, but every value here goes
// through `escapeHtml` (which covers `& < > " '`, enough for both text nodes and the one quoted
// attribute), and the viewer renders this in an iframe with `sandbox=""`, so scripts can't run even if
// the escaping were wrong. Keep both properties if you edit this: escape at every interpolation, and
// don't render anything the recipient didn't see.
const renderPushPreviewHtml = (payload: PushNotificationPayloadType): string => {
    const image = payload.image
        ? `<img src="${escapeHtml(payload.image)}" alt="" style="width:100%;max-height:180px;object-fit:cover;border-radius:8px;margin-top:8px">`
        : ''
    // The recipient sees this as a second bold line under the title on iOS, so a snapshot that drops
    // it doesn't match the notification that was delivered.
    const subtitle = payload.apns?.subtitle
        ? `<div style="font-size:15px;font-weight:600;color:#111;margin-bottom:2px">${escapeHtml(payload.apns.subtitle)}</div>`
        : ''
    const body = payload.body
        ? // nosemgrep: javascript.express.security.injection.raw-html-format.raw-html-format
          `<div style="font-size:14px;line-height:1.4;color:#2d2d2d">${escapeHtml(payload.body)}</div>`
        : ''
    // nosemgrep: javascript.express.security.injection.raw-html-format.raw-html-format
    return `<!doctype html><meta charset="utf-8"><div style="font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;padding:1rem;max-width:420px;margin:1rem auto"><div style="background:#f4f4f5;border-radius:14px;padding:12px 14px"><div style="font-size:15px;font-weight:600;color:#111;margin-bottom:2px">${escapeHtml(payload.title)}</div>${subtitle}${body}${image}</div></div>`
}

const oversizedPlaceholderHtml = (bytes: number): string => {
    const mb = (bytes / 1024 / 1024).toFixed(1)
    return `<!doctype html><meta charset="utf-8"><div style="padding:1rem;font-family:ui-sans-serif,system-ui,sans-serif;color:#555;max-width:640px;margin:2rem auto"><h3 style="margin:0 0 0.5rem">Email too large to capture</h3><p style="margin:0">The rendered email was ${mb}&nbsp;MB, which exceeds the ${MAX_HTML_BYTES / 1024 / 1024}&nbsp;MB capture limit. The send itself succeeded — this placeholder is stored so the &ldquo;View email&rdquo; link works, but the original body is not viewable here.</p></div>`
}

/**
 * Buffers rendered-email snapshots and flushes them as a single bulk Kafka
 * produce at the batch boundary — one round-trip per partition for the whole
 * batch instead of one per email.
 *
 * Flush is best-effort: on broker failure the batch is dropped and the
 * `cdp_message_assets_failed` counter is incremented. We prefer losing a
 * handful of Assets-tab rows during a Kafka incident over stalling the
 * whole CDP consumer (which would also re-trigger email sends on replay).
 */
export class MessageAssetsService {
    private queuedRows: MessageAssetRow[] = []

    constructor(private outputs: IngestionOutputs<MessageAssetsOutput>) {}

    // Returns null when there's no content (neither html nor text) or no action id —
    // the Assets API filters by `function_kind='hog_flow'` and keys off the action
    // node id, so a row without one is unreachable.
    buildRowForEmail(
        invocation: CyclotronJobInvocationHogFunction,
        params: CyclotronInvocationQueueParametersEmailType
    ): MessageAssetRow | null {
        if (!invocation.state.actionId) {
            return null
        }
        const body = params.html || (params.text ? wrapPlainTextAsHtml(params.text) : '')
        if (!body) {
            return null
        }
        const bodyBytes = Buffer.byteLength(body, 'utf8')
        let html = body
        if (bodyBytes > MAX_HTML_BYTES) {
            counterMessageAssetsTruncated.inc()
            html = oversizedPlaceholderHtml(bodyBytes)
        }
        return {
            team_id: invocation.teamId,
            function_kind: 'hog_flow',
            function_id: invocation.functionId,
            parent_run_id: invocation.parentRunId ?? '',
            invocation_id: invocation.id,
            action_id: invocation.state.actionId ?? '',
            kind: 'email',
            distinct_id: resolveEmailEngagementDistinctId(invocation) ?? '',
            person_id: invocation.state.globals.person?.id ?? '',
            recipient: params.to.email,
            subject: params.subject,
            status: 'sent',
            sent_at: isoMicroseconds(new Date()),
            version: microsecondsSinceEpoch(),
            is_deleted: 0,
            html,
        }
    }

    // One row per push step, not per channel. A step fans out to several provider integrations, but the
    // recipient experiences a single notification, so the person view should show one entry rather than
    // a near-identical row per channel. `platforms` is what actually took delivery, and the caller only
    // builds a row once at least one channel has, so this is only ever a delivered notification.
    buildRowForPush(
        invocation: CyclotronJobInvocationHogFunction,
        params: CyclotronInvocationQueueParametersSendPushNotificationType,
        platforms: string[]
    ): MessageAssetRow | null {
        if (!invocation.state.actionId) {
            return null
        }
        const payload = params.payload
        // Same rule as the email row: drop only when there is no content to show. A title-less push
        // still delivered something the recipient saw, so a body alone is worth capturing.
        if (!payload?.title && !payload?.body) {
            return null
        }
        // Nothing took delivery, so there is no notification a recipient saw to snapshot.
        if (platforms.length === 0) {
            return null
        }
        const recipient = params.distinctId
        return {
            team_id: invocation.teamId,
            function_kind: 'hog_flow',
            function_id: invocation.functionId,
            parent_run_id: invocation.parentRunId ?? '',
            invocation_id: invocation.id,
            action_id: invocation.state.actionId ?? '',
            kind: 'push',
            distinct_id: recipient,
            person_id: invocation.state.globals.person?.id ?? '',
            // The person, not the providers that carried it, so the Assets tab's RECIPIENT column means
            // the same thing for push as it does for email. Per-channel outcomes stay in the run log.
            recipient,
            subject: payload.title,
            status: 'sent',
            sent_at: isoMicroseconds(new Date()),
            version: microsecondsSinceEpoch(),
            is_deleted: 0,
            html: renderPushPreviewHtml(payload),
        }
    }

    queueInvocationResults(results: CyclotronJobInvocationResult[]): void {
        for (const result of results) {
            if (!result.messageAssets || result.messageAssets.length === 0) {
                continue
            }
            for (const row of result.messageAssets) {
                this.queuedRows.push(row)
            }
        }
        messageAssetsPendingRows.set(this.queuedRows.length)
    }

    async flush(): Promise<void> {
        if (this.queuedRows.length === 0) {
            return
        }
        const rows = this.queuedRows
        this.queuedRows = []
        messageAssetsPendingRows.set(0)

        try {
            await Promise.all(
                rows.map((row) =>
                    this.outputs.produce(MESSAGE_ASSETS_OUTPUT, {
                        // Partition by invocation_id so retried produces for the
                        // same asset collapse cleanly via the ReplacingMergeTree.
                        key: Buffer.from(row.invocation_id),
                        value: Buffer.from(safeClickhouseString(JSON.stringify(row))),
                    })
                )
            )
            const capturedByKind = new Map<MessageAssetRow['kind'], number>()
            for (const row of rows) {
                capturedByKind.set(row.kind, (capturedByKind.get(row.kind) ?? 0) + 1)
            }
            for (const [kind, count] of capturedByKind) {
                counterMessageAssetsCaptured.inc({ kind }, count)
            }
        } catch (error) {
            counterMessageAssetsFailed.inc(rows.length)
            logger.error('⚠️', `failed to flush message assets — dropping batch: ${error}`, {
                error: String(error),
                dropped: rows.length,
                // Row identifiers so the dropped sends can be reconstructed from logs
                // (the Assets tab won't have them and the rows can't be backfilled
                // automatically — the in-memory buffer is cleared above).
                rows: rows.map((r) => ({
                    team_id: r.team_id,
                    function_id: r.function_id,
                    invocation_id: r.invocation_id,
                    action_id: r.action_id,
                    person_id: r.person_id,
                    recipient: r.recipient,
                    sent_at: r.sent_at,
                })),
            })
            captureException(error)
        }
    }
}
