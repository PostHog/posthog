import {
    ActionFilter,
    FlattenedFunnelStep,
    FlattenedFunnelStepByBreakdown,
    FunnelStep,
    FunnelStepWithConversionMetrics,
} from '~/types'

/**
 * While we have both multi and single property breakdown modes.
 * And FlattenedFunnelStep['breakdowns'] property is being copied onto FlattenedFunnelStep['breakdown']
 * This might receive an Array of strings
 * @param stepBreakdown
 */
export function isBreakdownChildType(
    stepBreakdown: FlattenedFunnelStep['breakdown'] | Array<string | number>
): stepBreakdown is string | number | undefined | Array<string | number> {
    return Array.isArray(stepBreakdown) || ['string', 'number'].includes(typeof stepBreakdown)
}

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
