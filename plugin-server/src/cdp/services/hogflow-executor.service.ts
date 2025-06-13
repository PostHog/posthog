import { DateTime } from 'luxon'

import { HogFlow, HogFlowAction } from '../../schema/hogflow'
import { Person, PluginsServerConfig } from '../../types'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    LogEntry,
    MinimalAppMetric,
} from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils'
import { filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocationResult } from '../utils/invocation-utils'
import { HOG_FLOW_ACTION_RUNNERS } from './hogflows/actions'
import { HogFlowActionRunnerResult } from './hogflows/actions/types'

export const MAX_ACTION_STEPS_HARD_LIMIT = 1000

export function createHogFlowInvocation(
    globals: HogFunctionInvocationGlobals,
    hogFlow: HogFlow
): CyclotronJobInvocationHogFlow {
    return {
        id: new UUIDT().toString(),
        state: {
            personId: globals.person?.id ?? '',
            event: globals.event,
            variables: {},
        },
        teamId: hogFlow.team_id,
        functionId: hogFlow.id, // TODO: Include version?
        hogFlow,
        queue: 'hogflow',
        queuePriority: 1,
    }
}

export class HogFlowExecutorService {
    constructor(private config: PluginsServerConfig) {}

    buildHogFlowInvocations(
        hogFlows: HogFlow[],
        triggerGlobals: HogFunctionInvocationGlobals
    ): {
        invocations: CyclotronJobInvocationHogFlow[]
        metrics: MinimalAppMetric[]
        logs: LogEntry[]
    } {
        const metrics: MinimalAppMetric[] = []
        const logs: LogEntry[] = []
        const invocations: CyclotronJobInvocationHogFlow[] = []

        // TRICKY: The frontend generates filters matching the Clickhouse event type so we are converting back
        const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal(triggerGlobals)

        hogFlows.forEach((hogFlow) => {
            if (hogFlow.trigger.type !== 'event') {
                return
            }
            const filterResults = filterFunctionInstrumented({
                fn: hogFlow,
                filters: hogFlow.trigger.filters,
                filterGlobals,
                eventUuid: triggerGlobals.event.uuid,
            })

            // Add any generated metrics and logs to our collections
            metrics.push(...filterResults.metrics)
            logs.push(...filterResults.logs)

            if (!filterResults.match) {
                return
            }

            const invocation = createHogFlowInvocation(triggerGlobals, hogFlow)
            invocations.push(invocation)
        })

        return {
            invocations,
            metrics,
            logs,
        }
    }

    protected async getPerson(personId: string): Promise<Person | null> {
        // TODO: Implement via dedicated lazy loader service
        return null
    }

    private getCurrentAction(invocation: CyclotronJobInvocationHogFlow): HogFlowAction {
        const currentAction = invocation.state.currentAction
        if (!currentAction) {
            const triggerAction = invocation.hogFlow.actions.find((action) => action.type === 'trigger')
            if (!triggerAction) {
                throw new Error('No trigger action found')
            }
            return triggerAction
        }

        return this.getActionById(invocation, currentAction.id)
    }

    private getActionById(invocation: CyclotronJobInvocationHogFlow, actionId: string): HogFlowAction {
        const action = invocation.hogFlow.actions.find((action) => action.id === actionId)
        if (!action) {
            throw new Error(`Action ${actionId} not found`)
        }

        return action
    }

    private async runCurrentAction(invocation: CyclotronJobInvocationHogFlow): Promise<HogFlowActionRunnerResult> {
        const action = this.getCurrentAction(invocation)
        // Find the appropriate action from our registry
        const actionRunner = HOG_FLOW_ACTION_RUNNERS[action.type]
        if (!actionRunner) {
            throw new Error(`No action runner found for action type ${action.type}`)
        }

        // Validate the types are correct before calling

        // Call the action runner
        const result = await actionRunner.run(invocation, action)

        return Promise.resolve(result)
    }

    async execute(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        const loggingContext = {
            invocationId: invocation.id,
            hogFlowId: invocation.hogFlow.id,
            hogFlowName: invocation.hogFlow.name,
        }

        logger.debug('🦔', `[HogFlowExecutor] Executing hog flow`, loggingContext)

        const result = createInvocationResult<CyclotronJobInvocationHogFlow>(
            invocation,
            {
                queue: 'hogflow',
            },
            {
                finished: false,
            }
        )

        result.invocation.state.actionStepCount = invocation.state.actionStepCount ?? 0

        // TODO: Also derive max action step count from the hog flow
        try {
            while (!result.finished && result.invocation.state.actionStepCount < MAX_ACTION_STEPS_HARD_LIMIT) {
                const actionResult = await this.runCurrentAction(result.invocation)

                if (!actionResult.finished) {
                    // If the result isn't finished we _require_ that there is a `scheduledAt` param in order to delay the result
                    if (!actionResult.scheduledAt) {
                        throw new Error('Action result is not finished and no scheduledAt param is provided')
                    }

                    // TODO: Figure out what to do here...
                    result.finished = false
                    result.invocation.queueScheduledAt = actionResult.scheduledAt
                    // TODO: Do we also want to increment some meta context?
                    // TODO: Add a log here to indicate it is scheduled for later
                    break
                }

                if (actionResult.goToActionId) {
                    result.invocation.state.actionStepCount = (result.invocation.state.actionStepCount ?? 0) + 1
                    // Update the state to be going to the next action
                    result.invocation.state.currentAction = {
                        id: actionResult.goToActionId,
                        startedAt: DateTime.now(),
                    }
                    result.finished = false // Nothing new here but just to be sure
                    // TODO: Add a log here to indicate the outcome
                    break
                }

                // The action is finished so we move on
                // TODO: Add a log here to indicate the action lead to the end of the flow
                result.finished = true
                break
            }

            // * Save the iteration count in the state so we never get stuck in infinite loops
            // * Figure out how to invoke other hog functions...
        } catch (err) {
            // The final catch - in this case we are always just logging the final outcome
            result.error = err.message
            result.finished = true // Explicitly set to true to prevent infinite loops
            logger.error(
                '🦔',
                `[HogFlowExecutor] Error executing hog flow ${invocation.hogFlow.id} - ${invocation.hogFlow.name}. Event: '${invocation.state.event?.url}'`,
                err
            )
        }

        return Promise.resolve(result)
    }
}
