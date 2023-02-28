import { ActionFilter, FlattenedFunnelStepByBreakdown, FunnelStep, FunnelStepWithConversionMetrics } from '~/types'

export function getActionFilterFromFunnelStep(step: FunnelStep): ActionFilter {
    return {
        type: step.type,
        id: step.action_id,
        name: step.name,
        custom_name: step.custom_name,
        order: step.order,
        properties: [],
    }
}

export function getSignificanceFromBreakdownStep(
    breakdown: FlattenedFunnelStepByBreakdown,
    stepOrder: number
): FunnelStepWithConversionMetrics['significant'] {
    return breakdown.steps?.[stepOrder]?.significant
}
