import { HogFlowAction } from '../../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../../types'
import { checkConditions } from '../actions/conditional_branch'
import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerResult } from './action-handler.interface'

export class ConditionalBranchHandler implements ActionHandler {
    async execute(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'conditional_branch' | 'wait_until_condition' }>
    ): Promise<ActionHandlerResult> {
        const conditionResult = await checkConditions(
            invocation,
            action.type === 'conditional_branch'
                ? action
                : {
                      ...action,
                      type: 'conditional_branch',
                      config: {
                          conditions: [action.config.condition],
                          delay_duration: action.config.max_wait_duration,
                      },
                  }
        )

        if (conditionResult.scheduledAt) {
            return { scheduledAt: conditionResult.scheduledAt }
        } else if (conditionResult.nextAction) {
            return { nextAction: conditionResult.nextAction }
        }

        return { nextAction: findContinueAction(invocation) }
    }
}
