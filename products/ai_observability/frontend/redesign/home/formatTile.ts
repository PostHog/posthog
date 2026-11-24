import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { TraceMetricChangeUnitApi, TraceMetricKeyApi, type TraceMetricTileApi } from '../../generated/api.schemas'
import { formatCostUsd } from '../shared/formatCost'
import { formatLatencyMs } from '../trace/components/formatStats'

const MINUS = '−'
const NO_VALUE = '-'

const CHANGE_FORMAT: Record<TraceMetricChangeUnitApi, { suffix: string; decimals: number }> = {
    [TraceMetricChangeUnitApi.Percent]: { suffix: '%', decimals: 0 },
    [TraceMetricChangeUnitApi.Points]: { suffix: 'pp', decimals: 1 },
    [TraceMetricChangeUnitApi.Seconds]: { suffix: 's', decimals: 1 },
}

function orDash(value: number | null, format: (value: number) => string): string {
    return value === null ? NO_VALUE : format(value)
}

export function formatTileValue(key: TraceMetricKeyApi, value: number | null): string {
    switch (key) {
        case TraceMetricKeyApi.Cost:
            return orDash(value, formatCostUsd)
        case TraceMetricKeyApi.ErrorRate:
            return orDash(value, (fraction) => percentage(fraction, 1))
        case TraceMetricKeyApi.P95Latency:
            // formatLatencyMs gives "0ms", which reads as another unit at the base of an axis labelled in seconds.
            return orDash(value, (seconds) => (seconds === 0 ? '0s' : formatLatencyMs(seconds * 1000)))
        default:
            return humanFriendlyNumber(value)
    }
}

export function formatTileChange(change: number, unit: TraceMetricChangeUnitApi): string {
    const { suffix, decimals } = CHANGE_FORMAT[unit]
    const rounded = Number(change.toFixed(decimals))
    if (rounded === 0) {
        return `0${suffix}`
    }
    const magnitude = humanFriendlyNumber(Math.abs(rounded), decimals, decimals)
    return `${rounded < 0 ? MINUS : '+'}${magnitude}${suffix}`
}

export function formatTileDetail({
    detail,
    latencyQuantiles,
}: Pick<TraceMetricTileApi, 'detail' | 'latencyQuantiles'>): string | null {
    if (latencyQuantiles) {
        const { p50Seconds, p99Seconds } = latencyQuantiles
        return `p50 ${formatLatencyMs(p50Seconds * 1000)} · p99 ${formatLatencyMs(p99Seconds * 1000)}`
    }
    return detail
}

export function tileSlug(key: TraceMetricKeyApi): string {
    return key.replaceAll('_', '-')
}
