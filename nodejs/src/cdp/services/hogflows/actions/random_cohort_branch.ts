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
    const cohorts = action.config.cohorts ?? []
    if (cohorts.length === 0) {
        return findNextAction(invocation.hogFlow, action.id)
    }

    const random = Math.random() * 100 // 0-100
    let cumulativePercentage = 0

    for (const [index, cohort] of cohorts.entries()) {
        cumulativePercentage += cohort.percentage
        if (random <= cumulativePercentage) {
            return findNextAction(invocation.hogFlow, action.id, index)
        }
    }

    // If we somehow get here (shouldn't happen if percentages add up to 100),
    // go to the last cohort
    return findNextAction(invocation.hogFlow, action.id, cohorts.length - 1)
}
