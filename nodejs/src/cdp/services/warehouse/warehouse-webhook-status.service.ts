import { Gauge } from 'prom-client'

import { IngestionOutputs } from '../../../ingestion/outputs/ingestion-outputs'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { WAREHOUSE_WEBHOOK_DELIVERY_STATUS_OUTPUT, WarehouseWebhookDeliveryStatusOutput } from '../../outputs/outputs'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../../types'

const warehouseWebhookStatusPendingRecords = new Gauge({
    name: 'cdp_warehouse_webhook_status_pending_records',
    help: 'Number of warehouse webhook delivery status records queued and waiting to be flushed to Kafka.',
})

// Steady-state successful deliveries are throttled to one record per source per
// this window — a healthy high-volume source would otherwise write a row per
// delivery. Failures and the first success after a failure are never throttled
// (see `queue`), so the failing→healthy transition is always captured promptly.
const OK_THROTTLE_MS = 60_000

// Maximum length of the reason string we forward. Mirrors the spirit of the
// hog_invocation_results error_message truncation — enough to be actionable,
// bounded so a pathological body can't bloat the row.
const MAX_REASON_LENGTH = 200

export type WarehouseWebhookDeliveryStatusRecord = {
    team_id: number
    source_id: string
    schema_id: string
    http_status: number
    ok: 0 | 1
    reason: string
    timestamp: string // ClickHouse DateTime64(6) — 'YYYY-MM-DD HH:MM:SS.ffffff'
}

const isoMicroseconds = (date: Date): string => {
    // ClickHouse DateTime64(6) accepts 'YYYY-MM-DD HH:MM:SS.ffffff'.
    return date.toISOString().replace('T', ' ').replace('Z', '000')
}

const truncate = (value: string, max: number): string => (value.length <= max ? value : value.slice(0, max))

const deriveReason = (body: unknown): string => {
    if (typeof body === 'string') {
        return truncate(body, MAX_REASON_LENGTH)
    }
    if (body && typeof body === 'object') {
        const record = body as Record<string, unknown>
        const candidate = record.error ?? record.message
        if (typeof candidate === 'string') {
            return truncate(candidate, MAX_REASON_LENGTH)
        }
        try {
            return truncate(JSON.stringify(body), MAX_REASON_LENGTH)
        } catch {
            return ''
        }
    }
    return ''
}

/**
 * Collects warehouse source webhook delivery outcomes and flushes them to Kafka
 * (→ ClickHouse). The data import pipeline reads these to detect a webhook that
 * is persistently rejecting deliveries (e.g. a bad signing secret) and fail the
 * run with a non-retryable error instead of silently importing zero rows.
 *
 * Lifecycle mirrors `WarehouseWebhooksService`: callers push results in via
 * `queueInvocationResults` and trigger a batch emit via `flush()`. Only results
 * from `warehouse_source_webhook` hog functions that carry a `source_id` produce
 * a record — everything else is ignored.
 */
export class WarehouseWebhookStatusService {
    private queuedRecords: WarehouseWebhookDeliveryStatusRecord[] = []
    // Per-source throttle state for successful deliveries: last emitted ok flag
    // and the timestamp it was emitted at.
    private lastEmitBySource = new Map<string, { ok: boolean; ts: number }>()

    constructor(private outputs: IngestionOutputs<WarehouseWebhookDeliveryStatusOutput>) {}

    queueInvocationResults(results: CyclotronJobInvocationResult[]): void {
        for (const result of results) {
            const record = this.deriveRecord(result)
            if (record) {
                this.queue(record)
            }
        }
    }

    private deriveRecord(result: CyclotronJobInvocationResult): WarehouseWebhookDeliveryStatusRecord | null {
        const invocation = result.invocation
        if (!('hogFunction' in invocation)) {
            return null
        }

        const hogFunction = (invocation as CyclotronJobInvocationHogFunction).hogFunction
        if (hogFunction.type !== 'warehouse_source_webhook') {
            return null
        }

        const sourceId = hogFunction.inputs?.source_id?.value
        if (typeof sourceId !== 'string' || !sourceId) {
            // Can't attribute the delivery to a source — nothing to record.
            return null
        }

        const schemaIdValue = hogFunction.inputs?.schema_id?.value
        const schemaId = typeof schemaIdValue === 'string' ? schemaIdValue : ''

        // Prefer the hog function's HTTP response (signature/auth checks return
        // 4xx here); fall back to a runtime error as a 500.
        let status: number | undefined
        let body: unknown
        if (
            result.execResult &&
            typeof result.execResult === 'object' &&
            'httpResponse' in result.execResult &&
            (result.execResult as { httpResponse?: unknown }).httpResponse &&
            typeof (result.execResult as { httpResponse: unknown }).httpResponse === 'object'
        ) {
            const httpResponse = (result.execResult as { httpResponse: Record<string, unknown> }).httpResponse
            status = typeof httpResponse.status === 'number' ? httpResponse.status : undefined
            body = httpResponse.body
        }
        if (status === undefined) {
            if (result.error) {
                status = 500
                body = typeof result.error === 'string' ? result.error : 'Internal error'
            } else {
                // No HTTP response and no error (e.g. queued for async work) — nothing to record.
                return null
            }
        }

        const ok: 0 | 1 = status < 400 ? 1 : 0
        return {
            team_id: hogFunction.team_id,
            source_id: sourceId,
            schema_id: schemaId,
            http_status: status,
            ok,
            reason: ok ? '' : deriveReason(body),
            timestamp: isoMicroseconds(new Date()),
        }
    }

    queue(record: WarehouseWebhookDeliveryStatusRecord): void {
        if (!this.shouldEmit(record)) {
            return
        }
        this.queuedRecords.push(record)
        warehouseWebhookStatusPendingRecords.set(this.queuedRecords.length)
    }

    // Always emit failures and the first success after a non-success. Throttle
    // steady-state successes to one per source per `OK_THROTTLE_MS`.
    private shouldEmit(record: WarehouseWebhookDeliveryStatusRecord): boolean {
        const isOk = record.ok === 1
        if (!isOk) {
            this.lastEmitBySource.set(record.source_id, { ok: false, ts: Date.now() })
            return true
        }

        const previous = this.lastEmitBySource.get(record.source_id)
        const now = Date.now()
        if (previous && previous.ok && now - previous.ts < OK_THROTTLE_MS) {
            return false
        }
        this.lastEmitBySource.set(record.source_id, { ok: true, ts: now })
        return true
    }

    async flush(): Promise<void> {
        const records = this.queuedRecords
        this.queuedRecords = []
        warehouseWebhookStatusPendingRecords.set(0)

        if (records.length === 0) {
            return
        }

        await Promise.all(
            records.map((record) =>
                this.outputs
                    .produce(WAREHOUSE_WEBHOOK_DELIVERY_STATUS_OUTPUT, {
                        key: Buffer.from(`${record.team_id}:${record.source_id}`),
                        value: Buffer.from(JSON.stringify(record)),
                    })
                    .catch((error) => {
                        logger.error('Error producing warehouse webhook delivery status record', { error })
                        captureException(error)
                    })
            )
        )
    }
}
