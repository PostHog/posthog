import { humanizeNumber } from 'lib/utils'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { FunnelStep } from '~/types'

export function calcPercentage(numerator: number, denominator: number): number {
    return (numerator / denominator) * 100 || 0
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

// Gets last filled step if steps[index] is empty.
// Useful in calculating total and average times for total conversions where the last step has 0 count
export function getLastFilledStep(steps: FunnelStep[], index?: number): FunnelStep {
    const firstIndex = Math.min(steps.length, Math.max(0, index || steps.length - 1)) + 1
    return (
        steps
            .slice(0, firstIndex)
            .reverse()
            .find((s) => s.count > 0) || steps[0]
    )
}

export function humanizeStepCount(count: number): string {
    return count > 9999 ? humanizeNumber(count, 2) : count.toLocaleString()
}
