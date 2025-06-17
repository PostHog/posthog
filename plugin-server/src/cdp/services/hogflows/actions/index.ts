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
import { HogFlowActionResult, HogFlowActionRunnerResult } from './types'

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

    private findNextActionToRun(_invocation: CyclotronJobInvocationHogFlow): HogFlowAction | undefined {
        // Finds the next action to be run
        // TODO: Implement this!

        // Hack for now returns the exit action if it exists
        const exitAction = _invocation.hogFlow.actions.find((action) => action.type === 'exit')
        if (exitAction) {
            return exitAction
        }

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

    // NOTE: Keeping as a promise response for now as we will be adding async work later
    runCurrentAction(invocation: CyclotronJobInvocationHogFlow): Promise<HogFlowActionRunnerResult> {
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

            const nextAction = this.findNextActionToRun(invocation)
            if (!nextAction) {
                throw new Error('No next action found')
            }

            invocation.state.currentAction = {
                id: nextAction.id,
                startedAtTimestamp: DateTime.now().toMillis(),
            }
        }

        const currentActionId = invocation.state.currentAction?.id
        const action = invocation.hogFlow.actions.find((action) => action.id === currentActionId)
        if (!action) {
            throw new Error(`Action ${currentActionId} not found`)
        }

        if (this.shouldSkipAction(invocation, action)) {
            // Before we do anything check for filter conditions on the user
            return Promise.resolve({
                action,
                finished: true,
                goToActionId: this.findNextActionToRun(invocation),
            })
        }

        logger.debug('🦔', `[HogFlowActionRunner] Running action ${action.type}`, {
            action,
            invocation,
        })

        let result: HogFlowActionRunnerResult = {
            action,
            finished: true,
        }

        try {
            let actionResult: HogFlowActionResult
            switch (action.type) {
                case 'conditional_branch':
                    actionResult = this.hogFlowActionRunnerConditionalBranch.run(invocation, action)
                    break
                case 'delay':
                    actionResult = this.hogFlowActionRunnerDelay.run(invocation, action)
                    break
                case 'wait_until_condition':
                    actionResult = this.hogFlowActionRunnerWaitForCondition.run(invocation, action)
                    break
                case 'wait_until_time_window':
                    actionResult = this.hogFlowActionRunnerWaitUntilTimeWindow.run(action)
                    break
                case 'exit':
                    actionResult = {
                        finished: true,
                    }
                    break
                default:
                    throw new Error(`Action type ${action.type} not supported`)
            }

            if (actionResult.scheduledAt) {
                // All scheduled actions outcomes are set on the main result
                result.scheduledAt = actionResult.scheduledAt
            }

            if (actionResult.goToActionId) {
                // If the action is going to a specific action we need to find it and set it
                result.goToAction = this.findNextActionToRun(invocation)
            }

            if (!actionResult.finished) {
                // if the action result is _not_ finished then we set that to be the case on the main result
                // this indicates we shouldn't move forward to the next action
                result.finished = false
            }

            if (result.finished && !result.goToAction && result.action.type !== 'exit') {
                // Finally if the action  finished but didn't go to a specific action then we need to find the default next action to run to
                result.goToAction = this.findNextActionToRun(invocation)
            }
        } catch (error) {
            result = {
                ...result,
                error,
                finished: true,
            }
        }

        return Promise.resolve(result)
    }
}
