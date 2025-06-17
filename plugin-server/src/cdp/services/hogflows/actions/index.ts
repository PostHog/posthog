import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { Hub } from '~/types'
import { logger } from '~/utils/logger'

import { HogFlowActionRunnerCondition } from './condition.action'
import { HogFlowActionRunnerDelay } from './delay.action'
import { HogFlowActionRunnerResult } from './types'

export class HogFlowActionRunner {
    private hogFlowActionRunnerCondition: HogFlowActionRunnerCondition
    private hogFlowActionRunnerDelay: HogFlowActionRunnerDelay

    constructor(private hub: Hub) {
        this.hogFlowActionRunnerCondition = new HogFlowActionRunnerCondition()
        this.hogFlowActionRunnerDelay = new HogFlowActionRunnerDelay()
    }

    async runCurrentAction(invocation: CyclotronJobInvocationHogFlow): Promise<HogFlowActionRunnerResult> {
        if (!invocation.state.currentAction) {
            const triggerAction = invocation.hogFlow.actions.find((action) => action.type === 'trigger')
            if (!triggerAction) {
                throw new Error('No trigger action found')
            }
            // Se the current action to the trigger action
            invocation.state.currentAction = {
                id: triggerAction.id,
                startedAtTimestamp: DateTime.now().toMillis(),
            }

            // TODO: For the trigger action we need to assume that we have already been "started" this way and move on...
        }

        const currentActionId = invocation.state.currentAction?.id
        const action = invocation.hogFlow.actions.find((action) => action.id === currentActionId)
        if (!action) {
            throw new Error(`Action ${currentActionId} not found`)
        }

        logger.debug('🦔', `[HogFlowActionRunner] Running action ${action.type}`, {
            action,
            invocation,
        })

        let result: HogFlowActionRunnerResult

        switch (action.type) {
            case 'conditional_branch':
                result = await this.hogFlowActionRunnerCondition.run(invocation, action)
                break
            case 'delay':
                result = await this.hogFlowActionRunnerDelay.run(invocation, action)
                break
            default:
                throw new Error(`Action type ${action.type} not supported`)
        }

        // TODO: If the result is finished and no goToActionId is provided, we need to automatically find the next action to run

        if (result.finished && !result.goToActionId) {
            // TODO: Find the next action to run
        }

        return result
    }
}
