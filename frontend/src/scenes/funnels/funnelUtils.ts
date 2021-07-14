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
