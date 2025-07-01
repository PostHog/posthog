import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { Hub } from '~/types'
import { logger } from '~/utils/logger'

import { HogExecutorService } from '../../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../../managers/hog-function-template-manager.service'
import { ensureCurrentAction, findContinueAction, shouldSkipAction } from '../hogflow-utils'
import { HogFlowActionRunnerConditionalBranch } from './action.conditional_branch'
import { HogFlowActionRunnerDelay } from './action.delay'
import { HogFlowActionRunnerFunction } from './action.function'
import { HogFlowActionRunnerRandomCohortBranch } from './action.random_cohort_branch'
import { HogFlowActionRunnerWaitUntilTimeWindow } from './action.wait_until_time_window'
import { HogFlowActionResult, HogFlowActionRunnerResult } from './types'

export class HogFlowActionRunner {
    private hogFlowActionRunnerConditionalBranch: HogFlowActionRunnerConditionalBranch
    private hogFlowActionRunnerDelay: HogFlowActionRunnerDelay
    private hogFlowActionRunnerWaitUntilTimeWindow: HogFlowActionRunnerWaitUntilTimeWindow
    private hogFlowActionRunnerRandomCohortBranch: HogFlowActionRunnerRandomCohortBranch
    private hogFlowActionRunnerFunction: HogFlowActionRunnerFunction

    constructor(
        private hub: Hub,
        private hogFunctionExecutor: HogExecutorService,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService
    ) {
        this.hogFlowActionRunnerConditionalBranch = new HogFlowActionRunnerConditionalBranch()
        this.hogFlowActionRunnerDelay = new HogFlowActionRunnerDelay()
        this.hogFlowActionRunnerWaitUntilTimeWindow = new HogFlowActionRunnerWaitUntilTimeWindow()
        this.hogFlowActionRunnerRandomCohortBranch = new HogFlowActionRunnerRandomCohortBranch()
        this.hogFlowActionRunnerFunction = new HogFlowActionRunnerFunction(
            this.hub,
            this.hogFunctionExecutor,
            this.hogFunctionTemplateManager
        )
    }

    // NOTE: Keeping as a promise response for now as we will be adding async work later
    async runCurrentAction(invocation: CyclotronJobInvocationHogFlow): Promise<HogFlowActionRunnerResult> {
        const action = ensureCurrentAction(invocation)

        if (action.type === 'exit') {
            return {
                action,
                exited: true,
            }
        }

        if (await shouldSkipAction(invocation, action)) {
            // Before we do anything check for filter conditions on the user
            return {
                action,
                exited: false,
                goToAction: findContinueAction(invocation),
            }
        }

        logger.debug('🦔', `[HogFlowActionRunner] Running action ${action.type}`, {
            action,
            invocation,
        })

        try {
            let actionResult: HogFlowActionResult
            switch (action.type) {
                case 'conditional_branch':
                    actionResult = await this.hogFlowActionRunnerConditionalBranch.run(invocation, action)
                    break
                case 'delay':
                    actionResult = this.hogFlowActionRunnerDelay.run(invocation, action)
                    break
                case 'wait_until_condition':
                    actionResult = await this.hogFlowActionRunnerConditionalBranch.runWaitUntilCondition(
                        invocation,
                        action
                    )
                    break
                case 'wait_until_time_window':
                    actionResult = this.hogFlowActionRunnerWaitUntilTimeWindow.run(action)
                    break
                case 'random_cohort_branch':
                    actionResult = this.hogFlowActionRunnerRandomCohortBranch.run(invocation, action)
                    break
                case 'function':
                    actionResult = await this.hogFlowActionRunnerFunction.run(invocation, action)
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
            const nextAction = findContinueAction(invocation)

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
