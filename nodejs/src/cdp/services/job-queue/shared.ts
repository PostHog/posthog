import { Counter, Gauge, Histogram } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/config'

import { ValueMatcher } from '../../../types'
import { CdpConfig } from '../../config'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationResult,
    CyclotronJobQueueKind,
    CyclotronJobQueueSource,
} from '../../types'
import { IntegrationInputRefsRollout, replaceIntegrationInputsWithRefs } from '../../utils/integration-input-refs'

export const cdpJobSizeKb = new Histogram({
    name: 'cdp_cyclotron_job_size_kb',
    help: 'The size in kb of the jobs we are processing',
    buckets: [0, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, Infinity],
    labelNames: ['queue_kind'],
})

export const cdpJobSizeCompressedKb = new Histogram({
    name: 'cdp_cyclotron_job_size_compressed_kb',
    help: 'The size in kb of the compressed jobs we are processing',
    buckets: [0, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, Infinity],
    labelNames: ['queue_kind'],
})

const cdpCyclotronBatchUtilization = new Gauge({
    name: 'cdp_cyclotron_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['queue', 'source'],
})

const cdpCyclotronJobsProcessed = new Counter({
    name: 'cdp_cyclotron_jobs_processed',
    help: 'The number of jobs we are managing to process',
    labelNames: ['queue', 'source'],
})

/**
 * Records throughput and batch utilization for a consumed batch.
 * `cdp_cyclotron_batch_utilization` is consumed by KEDA to autoscale the cyclotron workers, so this
 * must be called on every batch — including empty ones — so idle workers report zero and can scale down.
 */
export function observeConsumedBatch(params: {
    queue: CyclotronJobQueueKind
    source: CyclotronJobQueueSource
    batchSize: number
    maxBatchSize: number
}): void {
    const { queue, source, batchSize, maxBatchSize } = params
    cdpCyclotronBatchUtilization.labels({ queue, source }).set(maxBatchSize > 0 ? batchSize / maxBatchSize : 0)
    cdpCyclotronJobsProcessed.inc({ queue, source }, batchSize)
}

/**
 * Strip transient data from invocation state before persisting.
 * Groups are always stripped. Person is stripped when stripPerson is true.
 * These are large and easily reloaded by the worker, so we avoid storing them.
 * When stripIntegrationSecrets is true, resolved integration inputs become references (see integration-input-refs).
 * Returns a new object if modifications are needed, otherwise the original.
 */
export function sanitizeInvocationForPersistence(
    invocation: CyclotronJobInvocation,
    { stripPerson, stripIntegrationSecrets }: { stripPerson?: boolean; stripIntegrationSecrets?: boolean } = {}
): CyclotronJobInvocation {
    const state = invocation.state
    if (!state) {
        return invocation
    }

    let newState = state
    const globals = state.globals
    if (globals) {
        const newGlobals = sanitizeGlobals(globals, { stripPerson, stripIntegrationSecrets })
        if (newGlobals !== globals) {
            newState = { ...newState, globals: newGlobals }
        }
    }

    // A workflow keeps the state of a paused function step, and that state carries the step's resolved inputs.
    const hogFunctionState = state.currentAction?.hogFunctionState
    if (stripIntegrationSecrets && hogFunctionState?.globals?.inputs) {
        const inputs = replaceIntegrationInputsWithRefs(hogFunctionState.globals.inputs)
        if (inputs !== hogFunctionState.globals.inputs) {
            newState = {
                ...newState,
                currentAction: {
                    ...state.currentAction,
                    hogFunctionState: { ...hogFunctionState, globals: { ...hogFunctionState.globals, inputs } },
                },
            }
        }
    }

    return newState === state ? invocation : { ...invocation, state: newState }
}

function sanitizeGlobals(
    globals: Record<string, any>,
    { stripPerson, stripIntegrationSecrets }: { stripPerson?: boolean; stripIntegrationSecrets?: boolean }
): Record<string, any> {
    const hasGroups = globals.groups && Object.keys(globals.groups).length > 0
    const hasPerson = stripPerson && globals.person
    const inputs =
        stripIntegrationSecrets && globals.inputs ? replaceIntegrationInputsWithRefs(globals.inputs) : globals.inputs

    if (!hasGroups && !hasPerson && inputs === globals.inputs) {
        return globals
    }

    const { groups: _g, person: _p, ...restGlobals } = globals
    const newGlobals: Record<string, any> = { ...restGlobals }

    if (!hasPerson && globals.person) {
        newGlobals.person = globals.person
    }
    if (inputs !== globals.inputs) {
        newGlobals.inputs = inputs
    }

    return newGlobals
}

/**
 * Creates a sanitizer that strips transient data before persisting.
 * Call once at construction time, use the returned functions on every queue operation.
 */
export function createInvocationSanitizer(
    config: Pick<CdpConfig, 'CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS'>,
    integrationRefsRollout: Pick<IntegrationInputRefsRollout, 'isEnabled'> = new IntegrationInputRefsRollout()
) {
    const stripPersonMatcher: ValueMatcher<number> = buildIntegerMatcher(
        config.CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS,
        true
    )

    return {
        sanitizeInvocations(invocations: CyclotronJobInvocation[]): CyclotronJobInvocation[] {
            const stripIntegrationSecrets = integrationRefsRollout.isEnabled()
            return invocations.map((inv) =>
                sanitizeInvocationForPersistence(inv, {
                    stripPerson: stripPersonMatcher(inv.teamId),
                    stripIntegrationSecrets,
                })
            )
        },

        sanitizeResults(results: CyclotronJobInvocationResult[]): CyclotronJobInvocationResult[] {
            const stripIntegrationSecrets = integrationRefsRollout.isEnabled()
            return results.map((result) => ({
                ...result,
                invocation: sanitizeInvocationForPersistence(result.invocation, {
                    stripPerson: stripPersonMatcher(result.invocation.teamId),
                    stripIntegrationSecrets,
                }),
            }))
        },
    }
}
