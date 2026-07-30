import { Counter } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { FINOPS_USAGE_OUTPUT, FinopsUsageOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { safeClickhouseString } from '~/common/utils/db/utils'
import { captureException } from '~/common/utils/posthog'
import { castTimestampOrNow } from '~/common/utils/utils'

import { TimestampFormat } from '../../types'

const finopsUsageMeterQueuedCounter = new Counter({
    name: 'finops_usage_meter_queued_total',
    help: 'FinOps usage meters queued — counted before in-memory dedup.',
    labelNames: ['product', 'billable_unit'],
})

const finopsUsageMeterFlushedCounter = new Counter({
    name: 'finops_usage_meter_flushed_total',
    help: 'Unique FinOps usage meter rows produced to Kafka after in-memory dedup.',
    labelNames: ['product', 'billable_unit'],
})

// The meter swallows its own errors to stay non-blocking, so failures are otherwise invisible
// on dashboards (only in exception tracking). This counter makes them alertable; `operation`
// distinguishes a buffering failure (queue) from a produce failure (flush).
const finopsUsageMeterErrorsCounter = new Counter({
    name: 'finops_usage_meter_errors_total',
    help: 'FinOps usage meter errors, swallowed to keep metering non-blocking.',
    labelNames: ['operation'],
})

/**
 * One usage-meter row, matching the ClickHouse `usage_meters` schema
 * (posthog/models/finops/usage_meters.py). The caller supplies the billable unit,
 * the quantity, and whatever attribution/sub-dimensions it has at the chokepoint;
 * `quantity`, `duration_ms`, and `count` accumulate, everything else is identity.
 */
export interface FinopsUsageMeterInput {
    product: string
    billableUnit: string
    quantity: number
    teamId?: number
    orgId?: string
    feature?: string
    system?: string
    workload?: string
    resourceId?: string
    durationMs?: number
    count?: number
    costUnit?: string
    costQuantity?: number
    team?: string
    costType?: string
    userId?: number
    traceId?: string
}

export interface FinopsEventOutputMeterInput {
    output: 'events' | 'ai_events'
    teamId: number
    orgId: string
    byteLength: number
    resourceId: string
}

export interface FinopsCapturedEventMeterInput {
    teamId: number
    orgId: string
    byteLength: number
    resourceId: string
}

export interface FinopsUsageMeterOptions {
    /** When false (the default) queue() and flush() are no-ops — the emitter is opt-in per consumer, env-controlled. */
    enabled?: boolean
}

type AccumulatedMeter = {
    product: string
    billableUnit: string
    teamId: number
    orgId: string
    feature: string
    system: string
    workload: string
    resourceId: string
    quantity: number
    durationMs: number
    count: number
    costUnit: string
    costQuantity: number
    team: string
    costType: string
    userId: number
    traceId: string
}

/**
 * Dedupes FinOps usage meters on `queue`, produces them on `flush`.
 *
 * Shared by the ingestion and CDP consumers. Modeled on `AppMetricsAggregator`: the
 * Kafka routing (producer + topic) is injected as an `IngestionOutputs` registry that
 * must include `FINOPS_USAGE_OUTPUT`; there is no owned lifecycle or background timer —
 * each call site `flush()`es at the end of its own batch. Usage only, never dollars.
 */
export class FinopsUsageMeter {
    private buffer = new Map<string, AccumulatedMeter>()
    private readonly enabled: boolean

    constructor(
        private readonly outputs: IngestionOutputs<FinopsUsageOutput>,
        options: FinopsUsageMeterOptions = {}
    ) {
        this.enabled = options.enabled ?? false
    }

    queue(meter: FinopsUsageMeterInput): void {
        // Opt-in and fail-safe: metering must never block or break the work it measures, so a
        // disabled meter is a no-op and any error is captured rather than thrown at the caller.
        if (!this.enabled) {
            return
        }
        try {
            finopsUsageMeterQueuedCounter.inc({ product: meter.product, billable_unit: meter.billableUnit })
            const key = makeKey(meter)
            const existing = this.buffer.get(key)
            if (existing) {
                existing.quantity += meter.quantity
                existing.costQuantity += meter.costQuantity ?? 0
                existing.durationMs += meter.durationMs ?? 0
                existing.count += meter.count ?? 1
            } else {
                this.buffer.set(key, {
                    product: meter.product,
                    billableUnit: meter.billableUnit,
                    teamId: meter.teamId ?? 0,
                    orgId: meter.orgId ?? '',
                    feature: meter.feature ?? '',
                    system: meter.system ?? '',
                    workload: meter.workload ?? '',
                    resourceId: meter.resourceId ?? '',
                    quantity: meter.quantity,
                    durationMs: meter.durationMs ?? 0,
                    count: meter.count ?? 1,
                    costUnit: meter.costUnit ?? '',
                    costQuantity: meter.costQuantity ?? 0,
                    team: meter.team ?? '',
                    costType: meter.costType ?? '',
                    userId: meter.userId ?? 0,
                    traceId: meter.traceId ?? '',
                })
            }
        } catch (error) {
            finopsUsageMeterErrorsCounter.inc({ operation: 'queue' })
            captureException(error)
        }
    }

    queueEventOutput(event: FinopsEventOutputMeterInput): void {
        const dimensions =
            event.output === 'ai_events'
                ? { product: 'ai_observability', billableUnit: 'llm_events', team: 'ai-observability' }
                : { product: 'shared', billableUnit: 'events', team: 'ingestion' }

        this.queue({
            ...dimensions,
            teamId: event.teamId,
            orgId: event.orgId,
            quantity: 1,
            costUnit: 'bytes',
            costQuantity: event.byteLength,
            costType: 'cogs',
            system: 'warpstream',
            workload: `emit:${event.output}`,
            resourceId: event.resourceId,
        })
    }

    queueCapturedEvent(event: FinopsCapturedEventMeterInput): void {
        this.queue({
            product: 'shared',
            billableUnit: 'events',
            team: 'ingestion',
            teamId: event.teamId,
            orgId: event.orgId,
            quantity: 1,
            costUnit: 'bytes',
            costQuantity: event.byteLength,
            costType: 'cogs',
            system: 'warpstream',
            workload: 'consume:capture',
            resourceId: event.resourceId,
        })
    }

    async flush(): Promise<void> {
        if (!this.enabled || this.buffer.size === 0) {
            return
        }
        // Drain before producing so a failed produce drops the batch (best-effort) rather than
        // letting the buffer grow unbounded across retries.
        const drained = [...this.buffer.values()]
        this.buffer.clear()

        try {
            const timestamp = castTimestampOrNow(null, TimestampFormat.ClickHouse)
            const environment = finopsEnvironment()
            const serviceName = defaultConfig.OTEL_SERVICE_NAME || ''
            // No partition key — ClickHouse re-aggregates and round-robin spreads load.
            const messages = drained.map((m) => ({
                value: Buffer.from(
                    safeClickhouseString(
                        JSON.stringify({
                            timestamp,
                            product: m.product,
                            team_id: m.teamId,
                            org_id: m.orgId,
                            feature: m.feature,
                            environment,
                            billable_unit: m.billableUnit,
                            quantity: m.quantity,
                            system: m.system,
                            workload: m.workload,
                            resource_id: m.resourceId,
                            duration_ms: m.durationMs,
                            service_name: serviceName,
                            count: m.count,
                            cost_unit: m.costUnit,
                            cost_quantity: m.costQuantity,
                            team: m.team,
                            cost_type: m.costType,
                            user_id: m.userId,
                            trace_id: m.traceId,
                        })
                    )
                ),
                key: null,
            }))
            await this.outputs.queueMessages(FINOPS_USAGE_OUTPUT, messages)

            for (const m of drained) {
                finopsUsageMeterFlushedCounter.inc({ product: m.product, billable_unit: m.billableUnit })
            }
        } catch (error) {
            finopsUsageMeterErrorsCounter.inc({ operation: 'flush' })
            captureException(error)
        }
    }
}

function finopsEnvironment(): string {
    const deployment = (defaultConfig.CLOUD_DEPLOYMENT || '').trim().toUpperCase()
    if (deployment === 'US') {
        return 'prod-us'
    }
    if (deployment === 'EU') {
        return 'prod-eu'
    }
    return 'dev'
}

function makeKey(m: FinopsUsageMeterInput): string {
    return [
        m.product,
        m.teamId ?? 0,
        m.orgId ?? '',
        m.feature ?? '',
        m.billableUnit,
        m.system ?? '',
        m.workload ?? '',
        m.resourceId ?? '',
        m.costUnit ?? '',
        m.team ?? '',
        m.costType ?? '',
        m.userId ?? 0,
        m.traceId ?? '',
    ].join(':')
}
