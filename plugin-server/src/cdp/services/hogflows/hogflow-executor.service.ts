import { DateTime } from 'luxon'

import { HogFlow } from '../../../schema/hogflow'
import { Hub } from '../../../types'
import { logger } from '../../../utils/logger'
import { UUIDT } from '../../../utils/utils'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    LogEntry,
    MinimalAppMetric,
} from '../../types'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../../utils/hog-function-filtering'
import { createInvocationResult } from '../../utils/invocation-utils'
import { HogFlowActionRunner } from './actions'

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

    async buildHogFlowInvocations(
        hogFlows: HogFlow[],
        triggerGlobals: HogFunctionInvocationGlobals
    ): Promise<{
        invocations: CyclotronJobInvocationHogFlow[]
        metrics: MinimalAppMetric[]
        logs: LogEntry[]
    }> {
        const metrics: MinimalAppMetric[] = []
        const logs: LogEntry[] = []
        const invocations: CyclotronJobInvocationHogFlow[] = []

        // TRICKY: The frontend generates filters matching the Clickhouse event type so we are converting back
        const filterGlobals = convertToHogFunctionFilterGlobal(triggerGlobals)

        for (const hogFlow of hogFlows) {
            if (hogFlow.trigger.type !== 'event') {
                continue
            }
            const filterResults = await filterFunctionInstrumented({
                fn: hogFlow,
                filters: hogFlow.trigger.filters,
                filterGlobals,
                eventUuid: triggerGlobals.event.uuid,
            })

            // Add any generated metrics and logs to our collections
            metrics.push(...filterResults.metrics)
            logs.push(...filterResults.logs)

            if (!filterResults.match) {
                continue
            }

            const invocation = createHogFlowInvocation(triggerGlobals, hogFlow)
            invocations.push(invocation)
        }

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
            {},
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

                // Track a metric for the outcome of the action result
                result.metrics.push({
                    team_id: invocation.hogFlow.team_id,
                    app_source_id: invocation.hogFlow.id,
                    instance_id: actionResult.action.id,
                    metric_kind: 'error' in actionResult ? 'failure' : 'success',
                    metric_name: 'error' in actionResult ? 'failed' : 'succeeded',
                    count: 1,
                })

                if ('error' in actionResult) {
                    result.logs.push({
                        level: 'error',
                        timestamp: DateTime.now(),
                        message: `Action ${actionResult.action.id} errored: ${String(actionResult.error)}`, // TODO: Is this enough detail?
                    })
                }

                if (actionResult.exited) {
                    result.finished = true

                    result.logs.push({
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: `Workflow completed`,
                    })
                    break
                }

                if (actionResult.scheduledAt) {
                    // If the result has scheduled for the future then we return that triggering a push back to the queue
                    result.invocation.queueScheduledAt = actionResult.scheduledAt
                    result.finished = false
                    result.logs.push({
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: `Workflow will pause until ${actionResult.scheduledAt.toISO()}`,
                    })
                }

                if ('goToAction' in actionResult) {
                    // Increment the action step count
                    result.invocation.state.actionStepCount = (result.invocation.state.actionStepCount ?? 0) + 1
                    // Update the state to be going to the next action
                    result.invocation.state.currentAction = {
                        id: actionResult.goToAction.id,
                        startedAtTimestamp: DateTime.now().toMillis(),
                    }
                    result.finished = false // Nothing new here but just to be sure

                    result.logs.push({
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: `Workflow moved to action '${actionResult.goToAction.name} (${actionResult.goToAction.id})'`,
                    })
                    continue
                }

                // This indicates that there is nothing more to be done in this execution so we should exit just in case
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

    // Like execute but does the complete flow, logging delays and async function calls rather than performing them
    async executeTest(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        const finalResult = createInvocationResult<CyclotronJobInvocationHogFlow>(
            invocation,
            {},
            {
                finished: false,
            }
        )

        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> | null = null

        let loopCount = 0

        while (!result || !result.finished) {
            logger.info('🦔', `[HogFlowExecutor] Executing hog flow invocation`, {
                loopCount,
            })
            loopCount++
            if (loopCount > 100) {
                // NOTE: This is hardcoded for now to prevent infinite loops. Later we should fix this properly.
                break
            }

            const nextInvocation: CyclotronJobInvocationHogFlow = result?.invocation ?? invocation

            result = await this.execute(nextInvocation)

            if (result?.invocation.queueScheduledAt) {
                finalResult.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: `Workflow will pause until ${result.invocation.queueScheduledAt.toISO()}`,
                })
            }

            result?.logs?.forEach((log) => {
                finalResult.logs.push(log)
            })
            result?.metrics?.forEach((metric) => {
                finalResult.metrics.push(metric)
            })
        }

        return finalResult
    }
}
