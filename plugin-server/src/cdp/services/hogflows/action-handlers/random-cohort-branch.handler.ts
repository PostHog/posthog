import { HogFlowAction } from '../../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../../types'
import { getRandomCohort } from '../actions/random_cohort_branch'
import { ActionHandler, ActionHandlerResult } from './action-handler.interface'

export class RandomCohortBranchHandler implements ActionHandler {
    execute(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'random_cohort_branch' }>
    ): ActionHandlerResult {
        const nextAction = getRandomCohort(invocation, action)
        return { nextAction }
    }
}
