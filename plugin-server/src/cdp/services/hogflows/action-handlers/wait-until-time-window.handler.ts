import { HogFlowAction } from '../../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../../types'
import { getWaitUntilTime } from '../actions/wait_until_time_window'
import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerResult } from './action-handler.interface'

export class WaitUntilTimeWindowHandler implements ActionHandler {
    execute(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'wait_until_time_window' }>
    ): ActionHandlerResult {
        const nextTime = getWaitUntilTime(action)
        return {
            nextAction: findContinueAction(invocation),
            scheduledAt: nextTime ?? undefined,
        }
    }
}
