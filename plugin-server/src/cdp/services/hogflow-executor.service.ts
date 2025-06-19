import { DateTime } from 'luxon'

import { HogFlow } from '../../schema/hogflow'
import { Hub } from '../../types'
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
import { HogFlowActionRunner } from './hogflows/actions'

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
    private hogFlowActionRunner: HogFlowActionRunner

    constructor(private hub: Hub) {
        this.hogFlowActionRunner = new HogFlowActionRunner(this.hub)
    }

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

        // TODO: Add early exit for exit conditions being met
        // Also load the person info for that and cache it on the invocation in a way that won't get serialized

        // NOTE: Todo this right we likely want to enrich the invocation here or earlier with two things:
        // 1. The person object
        // 2. the converted filters object as it is likely to be used by many or all runners

        // TODO: Also derive max action step count from the hog flow
        try {
            while (!result.finished && result.invocation.state.actionStepCount < MAX_ACTION_STEPS_HARD_LIMIT) {
                const actionResult = await this.hogFlowActionRunner.runCurrentAction(result.invocation)

                if (!actionResult.finished) {
                    // If the result isn't finished we _require_ that there is a `scheduledAt` param in order to delay the result
                    if (!actionResult.scheduledAt) {
                        throw new Error('Action result is not finished and no scheduledAt param is provided')
                    }

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
                        startedAtTimestamp: DateTime.now().toMillis(),
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

            // NOTE: Purposefully wait for the next tick to ensure we don't block up the event loop
            await new Promise((resolve) => process.nextTick(resolve))
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
