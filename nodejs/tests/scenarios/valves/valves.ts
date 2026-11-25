import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import type { Definition } from '../cards/definitions'
import { CdpRole, ValveEntry } from '../cards/schema'
import type { RunManifest } from '../cloud/lease'
import { durationMs } from '../duration'
import type { Actuation, Environment } from '../environment/environment'
import type { Observation } from '../environment/failover'
import type { CyclotronProbe, Queue } from '../probe/cyclotron-probe'
import type { WriterSample } from '../probe/writer-probe'
import { AmbiguousParams, SesRejectParams, SesThrottleParams, WEBHOOK_HOST } from '../provider-edge'
import { heldAnswerRule, ruleOf } from '../provider-edge/faults'

export type ValveContext = {
    environment: Pick<Environment, 'actuate'>
    probe: Pick<CyclotronProbe, 'runningJobs'>
    teams: number[]
    commits: () => readonly WriterSample[]
    manifest?: RunManifest
}

export type ValveDefinition = Definition & {
    target: z.ZodType<string>
    strandsRunningJobs: boolean
    roleExitGraceMs?: number
    restarts?: readonly z.infer<typeof CdpRole>[]
    journalsIntent?: true
    apply(context: ValveContext, target: string, dose: unknown, holdMs: number, signal: AbortSignal): Promise<Actuation>
}

export type ValveTimelineEntry = {
    valve: string
    target: string
    requestedAt: string
    intentAt?: string
    appliedAt?: string
    observedAt?: string
    releasedAt?: string
    observations?: Observation[]
    releaseIntentAt?: string
    releaseObservations?: Observation[]
    releaseError?: string
    error?: string
}

export interface Valves {
    start(entries: ValveEntry[], context: ValveContext): Promise<void>
    releaseAll(): Promise<void>
    timeline(): ValveTimelineEntry[]
    refusal: AbortSignal
}

export const roleKill: ValveDefinition = {
    name: 'role.kill',
    params: z.object({}).strict(),
    target: CdpRole,
    strandsRunningJobs: true,
    apply: ({ environment }, target) => environment.actuate({ kind: 'kill', role: CdpRole.parse(target) }),
}

export const roleFreeze: ValveDefinition = {
    name: 'role.freeze',
    params: z.object({}).strict(),
    target: CdpRole,
    strandsRunningJobs: true,
    apply: ({ environment }, target) => environment.actuate({ kind: 'freeze', role: CdpRole.parse(target) }),
}

const ConnectionShare = z.object({ share: z.number().gt(0).max(1) }).strict()

export const pgDropConnections: ValveDefinition = {
    name: 'pg.drop_connections',
    params: ConnectionShare,
    target: z.literal('postgres'),
    strandsRunningJobs: false,
    roleExitGraceMs: 5000,
    apply: ({ environment }, _target, dose) =>
        environment.actuate({ kind: 'pg.terminate', share: ConnectionShare.parse(dose).share }),
}

const StatusCode = z.number().int().min(400).max(599)
const DestinationStatus = z.union([
    z.object({ code: StatusCode, count: z.number().int().min(1) }).strict(),
    z.object({ code: StatusCode, share: z.number().gt(0).max(1) }).strict(),
])

export const destStatus: ValveDefinition = {
    name: 'dest.status',
    params: DestinationStatus,
    target: z.literal(WEBHOOK_HOST),
    strandsRunningJobs: false,
    apply: ({ environment }, target, dose) => {
        const { code, ...amount } = DestinationStatus.parse(dose)
        const rule = ruleOf({ name: 'dest.status', params: { code }, match: { host: target }, dose: amount })
        return environment.actuate({ kind: 'edge.fault', rule })
    },
}

export const sesThrottle: ValveDefinition = {
    name: 'ses.throttle',
    params: SesThrottleParams,
    target: z.literal('ses'),
    strandsRunningJobs: false,
    apply: ({ environment }, _target, dose) =>
        environment.actuate({
            kind: 'edge.fault',
            rule: ruleOf({ name: 'ses.throttle', params: SesThrottleParams.parse(dose) }),
        }),
}

const SesRejectDose = z.object({ type: SesRejectParams.shape.type, share: z.number().gt(0).max(1).default(1) }).strict()

export const sesReject: ValveDefinition = {
    name: 'ses.reject',
    params: SesRejectDose,
    target: z.literal('ses'),
    strandsRunningJobs: false,
    apply: ({ environment }, _target, dose) => {
        const { type, share } = SesRejectDose.parse(dose)
        return environment.actuate({
            kind: 'edge.fault',
            rule: ruleOf({ name: 'ses.reject', params: { type }, dose: { share } }),
        })
    },
}

const AmbiguousDose = z.union([
    z.object({ accepted: AmbiguousParams.shape.accepted, count: z.number().int().min(1) }).strict(),
    z.object({ accepted: AmbiguousParams.shape.accepted, share: z.number().gt(0).max(1) }).strict(),
])

export const sesAmbiguous: ValveDefinition = {
    name: 'ses.ambiguous',
    params: AmbiguousDose,
    target: z.literal('ses'),
    strandsRunningJobs: false,
    apply: ({ environment }, _target, dose) => {
        const { accepted, ...amount } = AmbiguousDose.parse(dose)
        const rule = ruleOf({ name: 'ses.ambiguous', params: { accepted }, dose: amount })
        return environment.actuate({ kind: 'edge.fault', rule })
    },
}

export const destAmbiguous: ValveDefinition = {
    name: 'dest.ambiguous',
    params: AmbiguousDose,
    target: z.literal(WEBHOOK_HOST),
    strandsRunningJobs: false,
    apply: ({ environment }, target, dose) => {
        const { accepted, ...amount } = AmbiguousDose.parse(dose)
        const rule = ruleOf({ name: 'dest.ambiguous', params: { accepted }, match: { host: target }, dose: amount })
        return environment.actuate({ kind: 'edge.fault', rule })
    },
}

export const pgFailover: ValveDefinition = {
    name: 'pg.failover',
    params: z.object({}).strict(),
    target: z.literal('cyclotron'),
    strandsRunningJobs: false,
    roleExitGraceMs: 5000,
    restarts: CdpRole.exclude(['cdp-ses-webhooks']).options,
    journalsIntent: true,
    apply: ({ environment, commits, manifest }, _target, _dose, holdMs, signal) =>
        manifest === undefined
            ? Promise.reject(new Error('pg.failover runs only on a run host'))
            : environment.actuate({ kind: 'rds.failover', manifest, holdMs, commits, signal }),
}

export const VALVES: ValveDefinition[] = [
    roleKill,
    roleFreeze,
    pgDropConnections,
    pgFailover,
    destStatus,
    sesThrottle,
    sesReject,
    sesAmbiguous,
    destAmbiguous,
]

const POLL_MS = 1000

function neverAppliedOf({ when }: ValveEntry): string {
    if (when === undefined) {
        return 'never applied: released before its offset'
    }
    return when.name === 'edge_accepted'
        ? `never applied: edge_accepted on ${when.params.channel} did not happen before the drive ended`
        : `never applied: running_on_queue ${when.params.queue} at least ${when.params.atLeast} did not hold before the drive ended`
}

const now = (): string => new Date().toISOString()

export function createValves({ pollMs = POLL_MS } = {}): Valves {
    const entries: ValveTimelineEntry[] = []
    const running: Promise<void>[] = []
    const released = new AbortController()
    const refusals = new AbortController()
    let releasing: Promise<void> | undefined

    const run = async (entry: ValveEntry, context: ValveContext, record: ValveTimelineEntry): Promise<void> => {
        let probeFailure: string | undefined
        const runningJobs = (queue: Queue): Promise<number> =>
            context.probe.runningJobs({ teams: context.teams, queues: [queue] }).then(
                (jobs) => {
                    probeFailure = undefined
                    return jobs
                },
                (error: unknown) => {
                    probeFailure = (error as Error).message
                    return 0
                }
            )
        const withProbeFailure = (error: string): string =>
            probeFailure === undefined ? error : `${error}; the probe last failed: ${probeFailure}`

        let boundary: Actuation | undefined
        const releaseBoundary = async (): Promise<void> => {
            const holding = boundary
            boundary = undefined
            await holding?.release().catch((error: unknown) => {
                record.error = [record.error, (error as Error).message].filter(Boolean).join('; ')
            })
        }

        const due = async (): Promise<boolean> => {
            if (entry.at !== undefined) {
                await sleep(durationMs(entry.at), undefined, { signal: released.signal }).catch(() => undefined)
                return true
            }
            if (entry.when!.name === 'edge_accepted') {
                boundary = await context.environment.actuate({ kind: 'edge.fault', rule: heldAnswerRule() })
                if (boundary.accepted === undefined) {
                    throw new Error('the edge cannot say when it accepted a request')
                }
                return boundary.accepted(released.signal)
            }
            const { queue, atLeast } = entry.when!.params
            while (!released.signal.aborted) {
                if ((await runningJobs(queue)) >= atLeast) {
                    return true
                }
                await sleep(pollMs, undefined, { signal: released.signal }).catch(() => undefined)
            }
            return false
        }

        const isDue = await due().catch((error: unknown) => {
            record.error = (error as Error).message
            return false
        })
        if (!isDue || released.signal.aborted) {
            record.error ??= withProbeFailure(
                isDue && entry.when?.name === 'edge_accepted'
                    ? 'never applied: the drive ended before the valve applied'
                    : neverAppliedOf(entry)
            )
            await releaseBoundary()
            return
        }
        const definition = VALVES.find(({ name }) => name === entry.valve)!
        let actuation: Actuation | undefined
        const journal = (): void => {
            const { unobserved, ...journalled } = actuation?.journal?.() ?? {}
            Object.assign(record, journalled)
            if (unobserved !== undefined) {
                record.error = unobserved
            }
        }
        try {
            if (!definition.journalsIntent) {
                record.intentAt = now()
            }
            actuation = await definition.apply(
                context,
                entry.target,
                entry.dose,
                durationMs(entry.for),
                released.signal
            )
            record.appliedAt = now()
            journal()
            const held = AbortSignal.any([released.signal, AbortSignal.timeout(durationMs(entry.for))])
            const observed = await actuation.observed(held)
            journal()
            if (!observed) {
                record.error ??= 'applied but not observed'
                if (actuation.refused?.()) {
                    refusals.abort({ ...record })
                }
            } else if (
                entry.when?.name === 'running_on_queue' &&
                definition.strandsRunningJobs &&
                (await runningJobs(entry.when.params.queue)) < entry.when.params.atLeast
            ) {
                record.error = withProbeFailure(
                    `applied after running_on_queue ${entry.when.params.queue} at least ${entry.when.params.atLeast} stopped holding`
                )
            } else {
                record.observedAt = now()
            }
            if (!held.aborted) {
                await new Promise((resolve) => held.addEventListener('abort', resolve, { once: true }))
            }
        } catch (error) {
            record.error = (error as Error).message
        } finally {
            await releaseBoundary()
            if (actuation) {
                try {
                    await actuation.release()
                    record.releasedAt = now()
                    journal()
                } catch (error) {
                    record.error = [record.error, (error as Error).message].filter(Boolean).join('; ')
                }
            }
        }
    }

    return {
        start(valveEntries, context) {
            for (const entry of valveEntries) {
                const record: ValveTimelineEntry = { valve: entry.valve, target: entry.target, requestedAt: now() }
                entries.push(record)
                running.push(run(entry, context, record))
            }
            return Promise.resolve()
        },

        releaseAll: () =>
            (releasing ??= (async () => {
                released.abort()
                await Promise.all(running)
            })()),

        timeline: () => entries.map((entry) => ({ ...entry })),

        refusal: refusals.signal,
    }
}
