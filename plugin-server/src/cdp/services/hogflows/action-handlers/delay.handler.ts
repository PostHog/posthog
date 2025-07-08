import { HogFlowAction } from '../../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../../types'
import { calculatedScheduledAt } from '../actions/delay'
import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerResult } from './action-handler.interface'

export class DelayHandler implements ActionHandler {
    execute(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'delay' }>
    ): ActionHandlerResult {
        const nextScheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp
        )

        return {
            nextAction: findContinueAction(invocation),
            scheduledAt: nextScheduledAt ?? undefined,
        }
    }
}
