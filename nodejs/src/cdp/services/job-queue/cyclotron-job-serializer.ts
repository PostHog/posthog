import { Histogram } from 'prom-client'

import { parseJSON } from '../../../utils/json-parse'
import { logger } from '../../../utils/logger'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { CyclotronV2DequeuedJob, CyclotronV2JobInit } from '../cyclotron-v2'

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

/**
 * The single JSON blob stored in the postgres-v2 `state` BYTEA column.
 * Mirrors the Kafka wire format — everything lives under one object.
 */
type SerializedV2JobState = {
    state: CyclotronJobInvocation['state']
    queueParameters?: CyclotronJobInvocation['queueParameters']
    queueMetadata?: CyclotronJobInvocation['queueMetadata']
}

/**
 * Globals fields that are never persisted to a queue: `groups` and `person`
 * are re-hydrated by the worker, `inputs` is rebuilt by the executor against
 * the current function config. Storing them only inflates the payload.
 */
const DERIVED_GLOBALS_KEYS: readonly string[] = ['inputs', 'person', 'groups']

function stripDerivedGlobals(globals: Record<string, any>): { globals: Record<string, any>; changed: boolean } {
    let changed = false
    const result: Record<string, any> = {}
    for (const key of Object.keys(globals)) {
        if (DERIVED_GLOBALS_KEYS.includes(key)) {
            changed = true
            continue
        }
        result[key] = globals[key]
    }
    return { globals: result, changed }
}

function serializeV2StateBlob(invocation: CyclotronJobInvocation): Buffer {
    const blob: SerializedV2JobState = {
        state: invocation.state,
        queueParameters: invocation.queueParameters ?? undefined,
        queueMetadata: invocation.queueMetadata ?? undefined,
    }
    return Buffer.from(JSON.stringify(blob))
}

type LookupColumnSource = {
    person?: { id?: string }
    state?: {
        event?: { distinct_id?: string }
        personId?: string
        currentAction?: { id?: string }
    } | null
}

export function extractDistinctId(invocation: CyclotronJobInvocation): string | null {
    return (invocation as LookupColumnSource).state?.event?.distinct_id || null
}

export function extractPersonId(invocation: CyclotronJobInvocation): string | null {
    const inv = invocation as LookupColumnSource
    return inv.person?.id || inv.state?.personId || null
}

export function extractActionId(invocation: CyclotronJobInvocation): string | null {
    return (invocation as LookupColumnSource).state?.currentAction?.id || null
}

/**
 * Owns serialization of cyclotron jobs to and from every queue backend
 * (Kafka, postgres-v2, legacy postgres).
 *
 * The guiding rule: a queue stores only the raw event data. `inputs`, `person`
 * and `groups` are always dropped on the way out — the worker re-hydrates
 * `person`/`groups` and the executor rebuilds `inputs` from the live function
 * config. This keeps every backend on the minimal wire format and means an
 * invocation always behaves exactly as designed, regardless of how it was
 * persisted or which backend it came from.
 */
export class CyclotronJobSerializer {
    /**
     * Drop derived data (`inputs`, `person`, `groups`) from invocation state.
     * Covers both a hog function's top-level globals and the nested hog
     * function context a hog flow carries while an action is mid-async.
     * Returns a new invocation only when something changed — never mutates.
     */
    stripForPersistence(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
        const state = invocation.state
        if (!state) {
            return invocation
        }

        let nextState = state
        let changed = false

        if (state.globals) {
            const stripped = stripDerivedGlobals(state.globals)
            if (stripped.changed) {
                nextState = { ...nextState, globals: stripped.globals }
                changed = true
            }
        }

        const nestedGlobals = state.currentAction?.hogFunctionState?.globals
        if (nestedGlobals) {
            const stripped = stripDerivedGlobals(nestedGlobals)
            if (stripped.changed) {
                nextState = {
                    ...nextState,
                    currentAction: {
                        ...nextState.currentAction,
                        hogFunctionState: {
                            ...nextState.currentAction.hogFunctionState,
                            globals: stripped.globals,
                        },
                    },
                }
                changed = true
            }
        }

        return changed ? { ...invocation, state: nextState } : invocation
    }

    stripResultsForPersistence(results: CyclotronJobInvocationResult[]): CyclotronJobInvocationResult[] {
        return results.map((result) => {
            const invocation = this.stripForPersistence(result.invocation)
            return invocation === result.invocation ? result : { ...result, invocation }
        })
    }

    /** Kafka wire format: the stripped invocation as a JSON string. */
    serializeForKafka(invocation: CyclotronJobInvocation): string {
        const stripped = this.stripForPersistence(invocation)
        // Copy explicit fields only, so transient props (hogFunction, person, …) never leak onto the wire.
        const clean: CyclotronJobInvocation = {
            id: stripped.id,
            teamId: stripped.teamId,
            functionId: stripped.functionId,
            parentRunId: stripped.parentRunId,
            state: stripped.state,
            queue: stripped.queue,
            queueParameters: stripped.queueParameters,
            queuePriority: stripped.queuePriority,
            queueScheduledAt: stripped.queueScheduledAt,
            queueMetadata: stripped.queueMetadata,
            queueSource: stripped.queueSource,
        }
        return JSON.stringify(clean)
    }

    /** Reconstruct a Kafka-sourced invocation from its already-decompressed value. */
    deserializeFromKafka(value: Buffer | string): CyclotronJobInvocation {
        const invocation = this.migrateLegacyInvocation(parseJSON(value.toString()))
        invocation.queueSource = 'kafka'
        return invocation
    }

    /** Postgres-v2: the full job-init record (stripped state blob + lookup columns). */
    serializeForPostgresV2(invocation: CyclotronJobInvocation): CyclotronV2JobInit {
        const stripped = this.stripForPersistence(invocation)
        const state = serializeV2StateBlob(stripped)
        cdpJobSizeKb.labels('postgres-v2').observe(state.length / 1024)
        cdpJobSizeCompressedKb.labels('postgres-v2').observe(state.length / 1024)

        return {
            id: stripped.id,
            teamId: stripped.teamId,
            functionId: stripped.functionId,
            queueName: stripped.queue,
            priority: stripped.queuePriority,
            scheduled: stripped.queueScheduledAt?.toJSDate() ?? new Date(),
            parentRunId: stripped.parentRunId ?? null,
            state,
            distinctId: extractDistinctId(stripped),
            personId: extractPersonId(stripped),
            actionId: extractActionId(stripped),
        }
    }

    /** Postgres-v2: just the stripped state blob, used by the reschedule path. */
    serializeStateForPostgresV2(invocation: CyclotronJobInvocation): Buffer {
        return serializeV2StateBlob(this.stripForPersistence(invocation))
    }

    deserializeFromPostgresV2(job: CyclotronV2DequeuedJob): CyclotronJobInvocation {
        let parsed: SerializedV2JobState = { state: null }

        if (job.state) {
            try {
                parsed = parseJSON(job.state.toString('utf-8'))
            } catch (e) {
                logger.error('Error parsing V2 job state', { error: String(e), jobId: job.id })
            }
        }

        const invocation: CyclotronJobInvocation = {
            id: job.id,
            teamId: job.teamId,
            functionId: job.functionId ?? '',
            queue: job.queueName as CyclotronJobQueueKind,
            queuePriority: job.priority,
            queueScheduledAt: job.scheduled ?? undefined,
            queueMetadata: parsed.queueMetadata ?? undefined,
            queueParameters: parsed.queueParameters ?? undefined,
            state: parsed.state,
            queueSource: 'postgres-v2',
        }

        if (job.parentRunId) {
            invocation.parentRunId = job.parentRunId
        }

        return invocation
    }

    // NOTE: https://github.com/PostHog/posthog/pull/32588 moved more things into the generic
    // "state" value. This migrates any legacy jobs to the new format. Can be removed shortly
    // after full release.
    private migrateLegacyInvocation(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
        const unknownInvocation = invocation as Record<string, any>

        if ('hogFunctionId' in unknownInvocation) {
            unknownInvocation.functionId = unknownInvocation.hogFunctionId
            unknownInvocation.state = {}
            delete unknownInvocation.hogFunctionId

            if ('vmState' in unknownInvocation) {
                unknownInvocation.state.vmState = unknownInvocation.vmState
                delete unknownInvocation.vmState
            }
            if ('globals' in unknownInvocation) {
                unknownInvocation.state.globals = unknownInvocation.globals
                delete unknownInvocation.globals
            }
            if ('timings' in unknownInvocation) {
                unknownInvocation.state.timings = unknownInvocation.timings
                delete unknownInvocation.timings
            }
        }

        return invocation
    }
}
