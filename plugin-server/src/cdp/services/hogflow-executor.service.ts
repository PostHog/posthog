import { PluginsServerConfig } from '../../types'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    HogFlow,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    LogEntry,
    MinimalAppMetric,
} from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils'
import { filterFunctionInstrumented } from '../utils/hog-function-filtering'

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

    buildHogFunctionInvocations(
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

            if (!invocation) {
                return
            }

            invocations.push(invocation)
            return
        })

        return {
            invocations,
            metrics,
            logs,
        }
    }

    execute(invocation: CyclotronJobInvocationHogFlow): CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> {
        const loggingContext = {
            invocationId: invocation.id,
            hogFlowId: invocation.hogFlow.id,
            hogFlowName: invocation.hogFlow.name,
        }

        logger.debug('🦔', `[HogExecutor] Executing function`, loggingContext)

        const result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> = {
            invocation,
            finished: true,
            capturedPostHogEvents: [],
            logs: [],
        }

        // TODO: Implement!

        return result
    }
}
