import { Counter, Gauge, Histogram } from 'prom-client'

import type { CommonConfig } from '~/common/config'
import { buildIntegerMatcher } from '~/common/config/config'

import { ValueMatcher } from '../../../types'
import { CdpConfig } from '../../config'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationResult,
    CyclotronJobQueueKind,
    CyclotronJobQueueSource,
    IntegrationType,
} from '../../types'
import { EncryptedFields } from '../../utils/encryption-utils'
import {
    IntegrationInputRefsRollout,
    IntegrationRefSigner,
    replaceIntegrationInputsWithRefs,
    signIntegrationRef,
} from '../../utils/integration-input-refs'

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
 * When integrationRefSigner is set, resolved integration inputs become signed references (see integration-input-refs).
 * When omitRebuildableInputs is set, inputs that the executor can build again are not stored (see rebuildable-inputs).
 * Returns a new object if modifications are needed, otherwise the original.
 */
export function sanitizeInvocationForPersistence(
    invocation: CyclotronJobInvocation,
    {
        stripPerson,
        integrationRefSigner,
        omitRebuildableInputs,
    }: { stripPerson?: boolean; integrationRefSigner?: IntegrationRefSigner; omitRebuildableInputs?: boolean } = {}
): CyclotronJobInvocation {
    const state = invocation.state
    if (!state) {
        return invocation
    }

    // The built inputs can hold a typed-in secret, or a secret that a template put into a header or a URL.
    // The key is removed, not emptied, so a worker without the rebuild builds the inputs on its rerun path
    // instead of running with no inputs.
    if (omitRebuildableInputs && state.inputsSource && state.globals?.inputs) {
        const { inputs: _inputs, ...globals } = state.globals
        return sanitizeInvocationForPersistence(
            { ...invocation, state: { ...state, globals, inputsOmitted: true } },
            { stripPerson, integrationRefSigner }
        )
    }

    const signRef = integrationRefSigner
        ? (inputKey: string, id: IntegrationType['id']) =>
              signIntegrationRef(integrationRefSigner, invocation.teamId, inputKey, id)
        : undefined

    let newState = state
    const globals = state.globals
    if (globals) {
        const newGlobals = sanitizeGlobals(globals, { stripPerson, signRef })
        if (newGlobals !== globals) {
            newState = { ...newState, globals: newGlobals }
        }
    }

    // A workflow keeps the state of a paused function step, and that state carries the step's resolved inputs.
    const hogFunctionState = state.currentAction?.hogFunctionState
    if (signRef && hogFunctionState?.globals?.inputs) {
        const inputs = replaceIntegrationInputsWithRefs(hogFunctionState.globals.inputs, signRef)
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
    {
        stripPerson,
        signRef,
    }: { stripPerson?: boolean; signRef?: (inputKey: string, id: IntegrationType['id']) => string }
): Record<string, any> {
    const hasGroups = globals.groups && Object.keys(globals.groups).length > 0
    const hasPerson = stripPerson && globals.person
    const inputs =
        signRef && globals.inputs ? replaceIntegrationInputsWithRefs(globals.inputs, signRef) : globals.inputs

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
    config: Pick<CdpConfig, 'CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS'> & Pick<CommonConfig, 'ENCRYPTION_SALT_KEYS'>,
    integrationRefsRollout: Pick<IntegrationInputRefsRollout, 'isEnabled'> = new IntegrationInputRefsRollout(),
    integrationRefSigner: IntegrationRefSigner = new EncryptedFields(config.ENCRYPTION_SALT_KEYS)
) {
    const stripPersonMatcher: ValueMatcher<number> = buildIntegerMatcher(
        config.CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS,
        true
    )

    return {
        sanitizeInvocations(invocations: CyclotronJobInvocation[]): CyclotronJobInvocation[] {
            const enabled = integrationRefsRollout.isEnabled()
            return invocations.map((inv) =>
                sanitizeInvocationForPersistence(inv, {
                    stripPerson: stripPersonMatcher(inv.teamId),
                    integrationRefSigner: enabled ? integrationRefSigner : undefined,
                    omitRebuildableInputs: enabled,
                })
            )
        },

        sanitizeResults(results: CyclotronJobInvocationResult[]): CyclotronJobInvocationResult[] {
            const enabled = integrationRefsRollout.isEnabled()
            return results.map((result) => ({
                ...result,
                invocation: sanitizeInvocationForPersistence(result.invocation, {
                    stripPerson: stripPersonMatcher(result.invocation.teamId),
                    integrationRefSigner: enabled ? integrationRefSigner : undefined,
                    omitRebuildableInputs: enabled,
                }),
            }))
        },
    }
}
