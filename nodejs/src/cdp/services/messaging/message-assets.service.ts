import { Counter, Gauge } from 'prom-client'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
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
    help: 'Asset captures that failed at Kafka produce. Unlike logs/metrics this is load-bearing data: a failed flush throws so the consumer does not commit, the batch is redelivered, and the dedup via ReplacingMergeTree(version) absorbs the resulting duplicate produce.',
})

const messageAssetsPendingRows = new Gauge({
    name: 'cdp_message_assets_pending_rows',
    help: 'Message-asset rows queued in-memory waiting for the next flush. Resets to 0 after each flush.',
})

export interface MessageAssetsServiceConfig {
    MESSAGE_ASSETS_CAPTURE_ENABLED: boolean
}

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

/**
 * Buffers rendered-email snapshots and flushes them as a single bulk Kafka
 * produce at the batch boundary — one round-trip per partition for the whole
 * batch instead of one per email.
 *
 * Email assets are load-bearing for the workflow Assets tab, so unlike the
 * logs/metrics services this one rethrows on flush failure. The consumer's
 * `runBackgroundTasks` awaits the flush before the job-queue commits offsets,
 * so a broker outage stalls progress rather than silently dropping rows. On
 * crash mid-flush the batch is redelivered and re-produced with the same
 * `invocation_id` partition key — the destination ReplacingMergeTree collapses
 * the duplicate via `version`.
 */
export class MessageAssetsService {
    private queuedRows: MessageAssetRow[] = []

    constructor(
        private outputs: IngestionOutputs<MessageAssetsOutput>,
        private config: MessageAssetsServiceConfig
    ) {}

    // Returns null when capture is disabled, no content (neither html nor
    // text), or no action id — the Assets API filters by `function_kind='hog_flow'`
    // and keys off the action node id, so a row without one is unreachable.
    buildRowForEmail(
        invocation: CyclotronJobInvocationHogFunction,
        params: CyclotronInvocationQueueParametersEmailType
    ): MessageAssetRow | null {
        if (!this.config.MESSAGE_ASSETS_CAPTURE_ENABLED) {
            return null
        }
        if (!invocation.state.actionId) {
            return null
        }
        const body = params.html || (params.text ? wrapPlainTextAsHtml(params.text) : '')
        if (!body) {
            return null
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
            html: body,
        }
    }

    queueInvocationResults(results: CyclotronJobInvocationResult[]): void {
        for (const result of results) {
            if (!result.emailAssets || result.emailAssets.length === 0) {
                continue
            }
            for (const row of result.emailAssets) {
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
            counterMessageAssetsCaptured.inc({ kind: 'email' }, rows.length)
        } catch (error) {
            counterMessageAssetsFailed.inc(rows.length)
            logger.error('⚠️', `failed to flush message assets — stalling consumer to preserve durability: ${error}`, {
                error: String(error),
                queued: rows.length,
            })
            captureException(error)
            // Rethrow so the consumer does not commit offsets — the redelivered
            // batch re-produces with the same `invocation_id` + `version`, which
            // the ReplacingMergeTree dedupes.
            throw error
        }
    }
}
