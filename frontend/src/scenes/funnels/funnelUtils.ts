import { humanizeNumber } from 'lib/utils'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { FunnelStep } from '~/types'

export function calcPercentage(numerator: number, denominator: number): number {
    // Rounds to two decimal places
    return Math.round(((numerator / denominator) * 100 || 0) * 100) / 100
}

export function getReferenceStep(steps: FunnelStep[], stepReference: FunnelStepReference, index?: number): FunnelStep {
    // Step to serve as denominator of percentage calculations.
    // step[0] is full-funnel conversion, previous is relative.
    if (!index || index <= 0) {
        return steps[0]
    }
    switch (stepReference) {
        case FunnelStepReference.previous:
            return steps[index - 1]
        case FunnelStepReference.total:
        default:
            return steps[0]
    }
}

export function humanizeStepCount(count: number): string {
    return count > 9999 ? humanizeNumber(count, 2) : count.toLocaleString()
}
