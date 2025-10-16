import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

type Action = Extract<HogFlowAction, { type: 'random_cohort_branch' }>

export class RandomCohortBranchHandler implements ActionHandler {
    execute({
        invocation,
        action,
    }: ActionHandlerOptions<Extract<HogFlowAction, { type: 'random_cohort_branch' }>>): ActionHandlerResult {
        const nextAction = getRandomCohort(invocation, action)
        return { nextAction }
    }
}

export function getRandomCohort(invocation: CyclotronJobInvocationHogFlow, action: Action): HogFlowAction {
    const random = Math.random() * 100 // 0-100
    let cumulativePercentage = 0

    for (const [index, cohort] of action.config.cohorts.entries()) {
        cumulativePercentage += cohort.percentage
        if (random <= cumulativePercentage) {
            return findNextAction(invocation.hogFlow, action.id, index)
        }
    }

    // If we somehow get here (shouldn't happen if percentages add up to 100),
    // go to the last cohort
    return findNextAction(invocation.hogFlow, action.id, action.config.cohorts.length - 1)
}
