import { Counter } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { FINOPS_USAGE_OUTPUT, FinopsUsageOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { safeClickhouseString } from '~/common/utils/db/utils'
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

    constructor(private readonly outputs: IngestionOutputs<FinopsUsageOutput>) {}

    queue(meter: FinopsUsageMeterInput): void {
        finopsUsageMeterQueuedCounter.inc({ product: meter.product, billable_unit: meter.billableUnit })
        const key = makeKey(meter)
        const existing = this.buffer.get(key)
        if (existing) {
            existing.quantity += meter.quantity
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
            })
        }
    }

    async flush(): Promise<void> {
        if (this.buffer.size === 0) {
            return
        }
        const drained = [...this.buffer.values()]
        this.buffer.clear()

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
                    })
                )
            ),
            key: null,
        }))
        await this.outputs.queueMessages(FINOPS_USAGE_OUTPUT, messages)

        for (const m of drained) {
            finopsUsageMeterFlushedCounter.inc({ product: m.product, billable_unit: m.billableUnit })
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
    ].join(':')
}
