import type { BetsEntryApi } from '../generated/api.schemas'

export type BetRating = 'bad' | 'meh' | 'good' | 'amazing'

interface BetPerformance {
    progress: number
    rating: BetRating
}

type BetPerformanceInput = Pick<BetsEntryApi, 'baseline_value' | 'target' | 'direction' | 'status'> & {
    metric: Pick<BetsEntryApi['metric'], 'current'>
}

function rating(progress: number): BetRating {
    if (progress < 0) {
        return 'bad'
    }
    if (progress < 0.33) {
        return 'meh'
    }
    return progress < 0.8 ? 'good' : 'amazing'
}

export function betPerformance({
    baseline_value: baseline,
    target,
    direction,
    status,
    metric,
}: BetPerformanceInput): BetPerformance | null {
    const goal = Number.parseFloat(target ?? '')
    if (baseline === null || metric.current === null || !Number.isFinite(goal)) {
        return null
    }
    const sign = direction === 'decrease' ? -1 : 1
    const span = sign * (goal - baseline)
    if (span <= 0) {
        return null
    }
    const progress = (sign * (metric.current - baseline)) / span
    return { progress, rating: status === 'reached' ? 'amazing' : rating(progress) }
}
