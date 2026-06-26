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

/**
 * Buffers rendered-email snapshots and flushes them as a single bulk Kafka produce
 * at the batch boundary — so a workflow batch that sends N emails costs one
 * produce round-trip per partition, not N.
 *
 * Durability: email assets are load-bearing for the workflow Assets tab, so unlike
 * the logs/metrics services this one rethrows on flush failure. The consumer's
 * `runBackgroundTasks` awaits the flush before the Postgres job-queue commits
 * offsets, so a broker outage stalls progress rather than silently dropping rows.
 * On crash mid-flush the batch is redelivered, the emails re-send (the same
 * pre-existing duplicate-email risk we had with the fire-and-forget produce), and
 * the assets re-produce with the same `invocation_id` partition key — the
 * ReplacingMergeTree on the destination collapses them to one row.
 *
 * Gated by the global `MESSAGE_ASSETS_CAPTURE_ENABLED` kill-switch.
 */
export class MessageAssetsService {
    private queuedRows: MessageAssetRow[] = []

    constructor(
        private outputs: IngestionOutputs<MessageAssetsOutput>,
        private config: MessageAssetsServiceConfig
    ) {}

    /**
     * Builds the row from a successful email send. Returns null when the asset is
     * intentionally skipped (capture disabled, text-only email, or a standalone
     * email-destination send with no action id — the Assets API queries by
     * `function_kind='hog_flow'` keyed off the action node id, so capturing a row
     * with no action id would write data nothing can ever surface).
     *
     * Pure-ish builder so the email service can append the row directly onto
     * `result.emailAssets` without coupling to this service's buffer.
     */
    buildRowForEmail(
        invocation: CyclotronJobInvocationHogFunction,
        params: CyclotronInvocationQueueParametersEmailType
    ): MessageAssetRow | null {
        if (!this.config.MESSAGE_ASSETS_CAPTURE_ENABLED) {
            return null
        }
        if (!params.html) {
            return null
        }
        if (!invocation.state.actionId) {
            return null
        }
        return {
            team_id: invocation.teamId,
            // buildRowForEmail only returns a row for in-workflow email steps (an
            // action id is present), so these always attribute to the workflow.
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
            html: params.html,
        }
    }

    /**
     * Drains `result.emailAssets` from each invocation result into the internal
     * buffer. Mirrors `HogFunctionMonitoringService.queueInvocationResults` so the
     * fan-out in `InvocationResultsService` looks the same across sinks.
     */
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

    /**
     * Bulk-produces every queued row in parallel and awaits broker acks. Throws on
     * the first failure: callers (the consumer's `runBackgroundTasks`) MUST NOT
     * commit offsets if this throws, otherwise a broker outage would silently drop
     * load-bearing asset rows.
     */
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
                        // same asset land on the same partition and collapse
                        // cleanly via the ReplacingMergeTree.
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
            // Rethrow so the consumer does not commit offsets — the batch is
            // redelivered, emails re-send, assets re-produce, ReplacingMergeTree
            // dedupes on `invocation_id` + `version`. Better duplicate emails on
            // crash than lost asset rows.
            throw error
        }
    }
}
