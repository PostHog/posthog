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
        const currentActionId = invocation.state.currentActionId
        if (!currentActionId) {
            const triggerAction = invocation.hogFlow.actions.find((action) => action.type === 'trigger')
            if (!triggerAction) {
                throw new Error('No trigger action found')
            }
            return triggerAction
        }

        const action = invocation.hogFlow.actions.find((action) => action.id === currentActionId)
        if (!action) {
            throw new Error(`Action ${currentActionId} not found`)
        }

        return action
    }

    private async runCurrentAction(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
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

        const result = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hogflow',
        })

        try {
            // TODO: Should we use the invocation or the result one :thinking:
            const actionResult = await this.runCurrentAction(result.invocation)

            result.invocation.state.actionStepCount = (invocation.state.actionStepCount ?? 0) + 1

            // Update the state with the result and carry on in a loop as necessary

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
