import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'

import { findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

type Action = Extract<HogFlowAction, { type: 'random_cohort_branch' }>

export class RandomCohortBranchHandler implements ActionHandler {
    execute({
        invocation,
        action,
    }: ActionHandlerOptions<Extract<HogFlowAction, { type: 'random_cohort_branch' }>>): ActionHandlerResult {
        const nextAction = getRandomCohort(invocation, action)
        return { nextAction, result: { assigned_cohort: nextAction.id } }
    }
}

export function getRandomCohort(invocation: CyclotronJobInvocationHogFlow, action: Action): HogFlowAction {
    // Programmatically-authored nodes can be stored without their cohorts array (the API doesn't
    // require it on lenient saves); assign nothing and fall through the continue edge instead of
    // crashing the run.
    const cohorts = Array.isArray(action.config.cohorts) ? action.config.cohorts : []
    if (cohorts.length === 0) {
        return findNextAction(invocation.hogFlow, action.id)
    }

    const total = cohorts.reduce((sum, cohort) => sum + cohort.percentage, 0)
    // A zero or NaN total has no proportions to split by, so fall through like the empty case.
    if (!(total > 0)) {
        return findNextAction(invocation.hogFlow, action.id)
    }

    // Percentages act as relative weights, scaled by whatever they actually add up to. Summing to 100
    // is the same thing; not summing to 100 (an even N-way split of a count that doesn't divide 100,
    // say) still gives every cohort its intended share, rather than piling the shortfall onto the last
    // cohort or making later cohorts unreachable.
    const random = Math.random() * total
    let cumulativePercentage = 0

    for (const [index, cohort] of cohorts.entries()) {
        cumulativePercentage += cohort.percentage
        if (random <= cumulativePercentage) {
            return findNextAction(invocation.hogFlow, action.id, index)
        }
    }

    // Unreachable except for floating-point drift in the cumulative sum, where the last cohort is
    // the intended landing spot anyway.
    return findNextAction(invocation.hogFlow, action.id, cohorts.length - 1)
}
