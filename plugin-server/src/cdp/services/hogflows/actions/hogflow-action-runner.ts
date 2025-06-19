import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow, HogFunctionFilterGlobals } from '~/cdp/types'
import { convertToHogFunctionFilterGlobal } from '~/cdp/utils'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { HogFlowAction } from '~/schema/hogflow'
import { Hub } from '~/types'
import { logger } from '~/utils/logger'

import { HogFlowActionRunnerConditionalBranch } from './action.conditional_branch'
import { HogFlowActionRunnerDelay } from './action.delay'
import { HogFlowActionRunnerRandomCohortBranch } from './action.random_cohort_branch'
import { HogFlowActionRunnerWaitUntilTimeWindow } from './action.wait_until_time_window'
import { HogFlowActionResult, HogFlowActionRunnerResult } from './types'
import { findActionById, findNextAction } from './utils'

// TODO: Add a bunch of tests for this class!
export class HogFlowActionRunner {
    private hogFlowActionRunnerConditionalBranch: HogFlowActionRunnerConditionalBranch
    private hogFlowActionRunnerDelay: HogFlowActionRunnerDelay
    private hogFlowActionRunnerWaitUntilTimeWindow: HogFlowActionRunnerWaitUntilTimeWindow
    private hogFlowActionRunnerRandomCohortBranch: HogFlowActionRunnerRandomCohortBranch

    constructor(private hub: Hub) {
        this.hogFlowActionRunnerConditionalBranch = new HogFlowActionRunnerConditionalBranch()
        this.hogFlowActionRunnerDelay = new HogFlowActionRunnerDelay()
        this.hogFlowActionRunnerWaitUntilTimeWindow = new HogFlowActionRunnerWaitUntilTimeWindow()
        this.hogFlowActionRunnerRandomCohortBranch = new HogFlowActionRunnerRandomCohortBranch()
    }

    private findContinueAction(invocation: CyclotronJobInvocationHogFlow): HogFlowAction {
        const currentActionId = invocation.state.currentAction?.id
        if (!currentActionId) {
            throw new Error('Cannot find continue action without a current action')
        }

        const nextAction = findNextAction(invocation.hogFlow, currentActionId)
        if (!nextAction) {
            throw new Error(`Next action with id '${currentActionId}' not found`)
        }

        return nextAction
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
    async runCurrentAction(invocation: CyclotronJobInvocationHogFlow): Promise<HogFlowActionRunnerResult> {
        // HACK: Just keeping this async for now as we will definitely have async stuff here later
        await Promise.resolve()

        if (!invocation.state.currentAction) {
            const triggerAction = invocation.hogFlow.actions.find((action) => action.type === 'trigger')
            if (!triggerAction) {
                throw new Error('No trigger action found')
            }

            // Set the current action to the trigger action
            invocation.state.currentAction = {
                id: triggerAction.id,
                startedAtTimestamp: DateTime.now().toMillis(),
            }

            const nextAction = this.findContinueAction(invocation)
            if (!nextAction) {
                throw new Error('No next action found')
            }

            invocation.state.currentAction = {
                id: nextAction.id,
                startedAtTimestamp: DateTime.now().toMillis(),
            }
        }

        const currentActionId = invocation.state.currentAction?.id
        const action = findActionById(invocation.hogFlow, currentActionId)

        if (action.type === 'exit') {
            return {
                action,
                exited: true,
            }
        }

        if (this.shouldSkipAction(invocation, action)) {
            // Before we do anything check for filter conditions on the user
            return Promise.resolve({
                action,
                exited: false,
                goToAction: this.findContinueAction(invocation),
            })
        }

        logger.debug('🦔', `[HogFlowActionRunner] Running action ${action.type}`, {
            action,
            invocation,
        })

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
                    actionResult = this.hogFlowActionRunnerConditionalBranch.runWaitUntilCondition(invocation, action)
                    break
                case 'wait_until_time_window':
                    actionResult = this.hogFlowActionRunnerWaitUntilTimeWindow.run(action)
                    break
                case 'random_cohort_branch':
                    actionResult = this.hogFlowActionRunnerRandomCohortBranch.run(invocation, action)
                    break
                default:
                    throw new Error(`Action type ${action.type} not supported`)
            }

            // If we reach this point there is no way we are exiting

            if (!actionResult.done) {
                return {
                    action,
                    exited: false,
                    scheduledAt: actionResult.scheduledAt,
                }
            }

            if (actionResult.goToAction) {
                return {
                    action,
                    exited: false,
                    goToAction: actionResult.goToAction,
                    scheduledAt: actionResult.scheduledAt, // Optionally the action could have scheduled for the future (such as a delay)
                }
            }

            if (actionResult.scheduledAt) {
                // This is the case where the action isn't moving but wants to pause hence scheduling for later
                return {
                    action,
                    exited: false,
                    scheduledAt: actionResult.scheduledAt,
                }
            }

            // If we aren't moving forward, or pausing then we are just continuing to the next action
            const nextAction = this.findContinueAction(invocation)

            return {
                action,
                exited: false,
                goToAction: nextAction,
            }
        } catch (error) {
            return {
                action,
                error,
                exited: true,
            }
        }
    }
}
