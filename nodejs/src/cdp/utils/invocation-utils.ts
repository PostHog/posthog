// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema
import { DateTime } from 'luxon'

import { UUIDT } from '~/common/utils/utils'

import type { HogInputsService } from '../services/hog-inputs.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    LogEntry,
    MinimalAppMetric,
} from '../types'
import { HogFunctionType } from '../types'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from './hog-function-filtering'

export function createInvocation(
    globals: HogFunctionInvocationGlobalsWithInputs,
    hogFunction: HogFunctionType
): CyclotronJobInvocationHogFunction {
    return {
        id: new UUIDT().toString(),
        state: {
            globals,
            timings: [],
            attempts: 0,
        },
        teamId: hogFunction.team_id,
        functionId: hogFunction.id,
        hogFunction,
        queue: 'hog',
        queuePriority: 0,
    }
}

/**
 * Matches a batch of hog functions against one event's globals and builds an invocation per match,
 * resolving each one's inputs. Filter metrics/logs come back alongside for the caller to queue.
 */
export async function buildHogFunctionInvocations(
    hogInputsService: HogInputsService,
    hogFunctions: HogFunctionType[],
    triggerGlobals: HogFunctionInvocationGlobals
): Promise<{
    invocations: CyclotronJobInvocationHogFunction[]
    metrics: MinimalAppMetric[]
    logs: LogEntry[]
}> {
    const metrics: MinimalAppMetric[] = []
    const logs: LogEntry[] = []
    const invocations: CyclotronJobInvocationHogFunction[] = []

    // TRICKY: The frontend generates filters matching the Clickhouse event type so we are converting back
    const filterGlobals = convertToHogFunctionFilterGlobal(triggerGlobals)

    const _filterHogFunction = async (
        hogFunction: HogFunctionType,
        filters: HogFunctionType['filters'],
        filterGlobals: HogFunctionFilterGlobals
    ): Promise<boolean> => {
        const filterResults = await filterFunctionInstrumented({
            fn: hogFunction,
            filters,
            filterGlobals,
        })

        // Add any generated metrics and logs to our collections
        metrics.push(...filterResults.metrics)
        logs.push(...filterResults.logs)

        return filterResults.match
    }

    const _buildInvocation = async (
        hogFunction: HogFunctionType,
        additionalInputs?: HogFunctionType['inputs']
    ): Promise<CyclotronJobInvocationHogFunction | null> => {
        try {
            const globalsWithSource = {
                ...triggerGlobals,
                source: {
                    name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                    url: `${triggerGlobals.project.url}/functions/${hogFunction.id}/configuration/`,
                },
            }

            const globalsWithInputs = await hogInputsService.buildInputsWithGlobals(
                hogFunction,
                globalsWithSource,
                additionalInputs
            )

            return createInvocation(globalsWithInputs, hogFunction)
        } catch (error) {
            logs.push({
                team_id: hogFunction.team_id,
                log_source: 'hog_function',
                log_source_id: hogFunction.id,
                instance_id: new UUIDT().toString(), // random UUID, like it would be for an invocation
                timestamp: DateTime.now(),
                level: 'error',
                message: `Error building inputs for event ${triggerGlobals.event.uuid}: ${error.message}`,
            })

            metrics.push({
                team_id: hogFunction.team_id,
                app_source_id: hogFunction.id,
                metric_kind: 'failure',
                metric_name: 'inputs_failed',
                count: 1,
            })

            return null
        }
    }

    await Promise.all(
        hogFunctions.map(async (hogFunction) => {
            // We always check the top level filters
            if (!(await _filterHogFunction(hogFunction, hogFunction.filters, filterGlobals))) {
                return
            }

            // Check for non-mapping functions first
            if (!hogFunction.mappings) {
                const invocation = await _buildInvocation(hogFunction)
                if (!invocation) {
                    return
                }

                invocations.push(invocation)
                return
            }

            await Promise.all(
                hogFunction.mappings.map(async (mapping) => {
                    if (!(await _filterHogFunction(hogFunction, mapping.filters, filterGlobals))) {
                        return
                    }

                    const invocation = await _buildInvocation(hogFunction, mapping.inputs ?? {})
                    if (!invocation) {
                        return
                    }

                    invocations.push(invocation)
                })
            )
        })
    )

    return {
        invocations,
        metrics,
        logs,
    }
}

/**
 * Clones an invocation, removing all queue related values
 */

export function cloneInvocation<T extends CyclotronJobInvocation>(
    invocation: T,
    params: Pick<
        Partial<CyclotronJobInvocation>,
        'queue' | 'queuePriority' | 'queueMetadata' | 'queueScheduledAt' | 'queueParameters'
    > = {}
): T {
    return {
        ...invocation,
        // The target queue is typically the same as the source but can be overridden
        queue: params.queue ?? invocation.queue,
        // The source is kept from the invocation always as it is important for the job queue router
        queueSource: invocation.queueSource,
        // Metadata is only used from the invocation if the queue is staying the same
        queueMetadata:
            params.queueMetadata ?? (invocation.queue === params.queue ? invocation.queueMetadata : undefined),

        // Below params are always reset unless provided as overrides
        queueScheduledAt: params.queueScheduledAt ?? undefined,
        queuePriority: params.queuePriority ?? 0,
        queueParameters: params.queueParameters ?? undefined,
    }
}

/**
 * Safely creates an invocation result from an invocation, cloning it and resetting the relevant queue parameters
 */
export function createInvocationResult<T extends CyclotronJobInvocation>(
    invocation: CyclotronJobInvocation,
    invocationParams: Pick<
        Partial<CyclotronJobInvocation>,
        'queue' | 'queuePriority' | 'queueMetadata' | 'queueScheduledAt' | 'queueParameters'
    > = {},
    resultParams: Pick<
        Partial<CyclotronJobInvocationResult>,
        | 'finished'
        | 'capturedPostHogEvents'
        | 'warehouseWebhookPayloads'
        | 'messageAssets'
        | 'logs'
        | 'metrics'
        | 'error'
        | 'execResult'
    > = {}
): CyclotronJobInvocationResult<T> {
    return {
        // Clone the invocation for the result cleaned
        finished: true,
        capturedPostHogEvents: [],
        warehouseWebhookPayloads: [],
        messageAssets: [],
        logs: [],
        metrics: [],
        ...resultParams,
        invocation: cloneInvocation(invocation, invocationParams) as T,
    }
}
