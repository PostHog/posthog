// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema
import { UUIDT } from '../../utils/utils'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobalsWithInputs,
} from '../types'
import { HogFunctionType } from '../types'

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
        'finished' | 'capturedPostHogEvents' | 'logs' | 'metrics' | 'error'
    > = {}
): CyclotronJobInvocationResult<T> {
    return {
        // Clone the invocation for the result cleaned
        finished: true,
        capturedPostHogEvents: [],
        logs: [],
        metrics: [],
        ...resultParams,
        invocation: cloneInvocation(invocation, invocationParams) as T,
    }
}
