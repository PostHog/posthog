import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow, HogFunctionFilterGlobals } from '~/cdp/types'
import { convertToHogFunctionFilterGlobal } from '~/cdp/utils'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { HogFlowAction } from '~/schema/hogflow'
import { Hub } from '~/types'
import { logger } from '~/utils/logger'

import { HogFlowActionRunnerConditionalBranch } from './action.conditional_branch'
import { HogFlowActionRunnerDelay } from './action.delay'
import { HogFlowActionRunnerWaitForCondition } from './action.wait_for_condition'
import { HogFlowActionRunnerWaitUntilTimeWindow } from './action.wait_until_time_window'
import { HogFlowActionRunnerResult } from './types'

export class HogFlowActionRunner {
    private hogFlowActionRunnerConditionalBranch: HogFlowActionRunnerConditionalBranch
    private hogFlowActionRunnerDelay: HogFlowActionRunnerDelay
    private hogFlowActionRunnerWaitForCondition: HogFlowActionRunnerWaitForCondition
    private hogFlowActionRunnerWaitUntilTimeWindow: HogFlowActionRunnerWaitUntilTimeWindow

    constructor(private hub: Hub) {
        this.hogFlowActionRunnerConditionalBranch = new HogFlowActionRunnerConditionalBranch()
        this.hogFlowActionRunnerDelay = new HogFlowActionRunnerDelay()
        this.hogFlowActionRunnerWaitForCondition = new HogFlowActionRunnerWaitForCondition()
        this.hogFlowActionRunnerWaitUntilTimeWindow = new HogFlowActionRunnerWaitUntilTimeWindow()
    }

    private findNextActionToRun(_invocation: CyclotronJobInvocationHogFlow): string | undefined {
        // Finds the next action to be run

        // TODO: Implement this!

        return undefined
    }

    private shouldSkipAction(invocation: CyclotronJobInvocationHogFlow, action: HogFlowAction): boolean {
        if (!action.filters) {
            return false
        }

        // TODO: Make filterGlobals, person and groups something we load lazily onto the main invocation object to be re-used anywhere
        // this function isn't super cheap to run
        const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal({
            event: invocation.state.event, // TODO: Fix typing
            // TODO: Add person and groups!
            groups: {},
        })

        const filterResults = filterFunctionInstrumented({
            fn: invocation.hogFlow,
            filters: action.filters,
            filterGlobals,
            eventUuid: invocation.state.event.uuid,
        })

        return filterResults.match
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

        if (this.shouldSkipAction(invocation, action)) {
            // Before we do anything check for filter conditions on the user
            return {
                finished: true,
                goToActionId: this.findNextActionToRun(invocation),
            }
        }

        logger.debug('🦔', `[HogFlowActionRunner] Running action ${action.type}`, {
            action,
            invocation,
        })

        let result: HogFlowActionRunnerResult

        switch (action.type) {
            case 'conditional_branch':
                result = await this.hogFlowActionRunnerConditionalBranch.run(invocation, action)
                break
            case 'delay':
                result = await this.hogFlowActionRunnerDelay.run(invocation, action)
                break
            case 'wait_until_condition':
                result = await this.hogFlowActionRunnerWaitForCondition.run(invocation, action)
                break
            case 'wait_until_time_window':
                result = await this.hogFlowActionRunnerWaitUntilTimeWindow.run(invocation, action)
                break
            case 'exit':
                result = {
                    finished: true,
                }
                // We are truly finished here
                return result
            default:
                throw new Error(`Action type ${action.type} not supported`)
        }

        // TODO: If the result is finished and no goToActionId is provided, we need to automatically find the next action to run

        if (result.finished && !result.goToActionId) {
            // TODO: Find the next action to run
            result.goToActionId = this.findNextActionToRun(invocation)
        }

        return result
    }
}
