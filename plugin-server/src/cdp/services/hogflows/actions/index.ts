import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow } from '~/src/cdp/types'
import { Hub } from '~/src/types'

import { HogFlowActionRunnerCondition } from './condition.action'
import { HogFlowActionRunnerResult } from './types'

export class HogFlowActionRunner {
    private hogFlowActionRunnerCondition: HogFlowActionRunnerCondition

    constructor(private hub: Hub) {
        this.hogFlowActionRunnerCondition = new HogFlowActionRunnerCondition()
    }

    runCurrentAction(invocation: CyclotronJobInvocationHogFlow): Promise<HogFlowActionRunnerResult> {
        let currentAction = invocation.state.currentAction
        if (!currentAction) {
            const triggerAction = invocation.hogFlow.actions.find((action) => action.type === 'trigger')
            if (!triggerAction) {
                throw new Error('No trigger action found')
            }
            // Se the current action to the trigger action
            currentAction = invocation.state.currentAction = {
                id: triggerAction.id,
                startedAt: DateTime.now(),
            }

            // TODO: For the trigger action we need to assume that we have already been "started" this way and move on...
        }

        const action = invocation.hogFlow.actions.find((action) => action.id === currentAction.id)
        if (!action) {
            throw new Error(`Action ${currentAction.id} not found`)
        }

        switch (action.type) {
            case 'conditional_branch':
                return this.hogFlowActionRunnerCondition.run(invocation, action)
            default:
                throw new Error(`Action type ${action.type} not supported`)
        }
    }
}
