import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { TraceMetricChangeUnitApi, TraceMetricKeyApi } from '../../generated/api.schemas'
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
            return orDash(value, (seconds) => formatLatencyMs(seconds * 1000))
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
