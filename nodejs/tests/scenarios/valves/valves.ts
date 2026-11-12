import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import type { Definition } from '../cards/definitions'
import { CdpRole, ValveEntry } from '../cards/schema'
import { durationMs } from '../duration'
import type { Actuation, Environment } from '../environment/environment'
import type { CyclotronProbe, Queue } from '../probe/cyclotron-probe'
import { sesReject, sesThrottle } from './ses'

export type ValveContext = {
    environment: Pick<Environment, 'actuate'>
    probe: Pick<CyclotronProbe, 'runningJobs'>
    teams: number[]
    edgeUrl: string
}

export type ApplyContext = ValveContext & { pollMs: number; faultObservedWithinMs: number; signal: AbortSignal }

export type ValveDefinition = Definition & {
    target: z.ZodType<string>
    apply(context: ApplyContext, target: string, dose: unknown): Promise<Actuation>
}

export type ValveTimelineEntry = {
    valve: string
    target: string
    requestedAt: string
    appliedAt?: string
    observedAt?: string
    releasedAt?: string
    error?: string
}

export interface Valves {
    start(entries: ValveEntry[], context: ValveContext): Promise<void>
    releaseAll(): Promise<void>
    timeline(): ValveTimelineEntry[]
}

export const roleKill: ValveDefinition = {
    name: 'role.kill',
    params: z.object({}).strict(),
    target: CdpRole,
    apply: ({ environment }, target) => environment.actuate({ kind: 'kill', role: CdpRole.parse(target) }),
}

export const VALVES: ValveDefinition[] = [roleKill, sesThrottle, sesReject]

const POLL_MS = 1000
const FAULT_OBSERVED_WITHIN_MS = 30_000

const now = (): string => new Date().toISOString()

export function createValves({ pollMs = POLL_MS, faultObservedWithinMs = FAULT_OBSERVED_WITHIN_MS } = {}): Valves {
    const entries: ValveTimelineEntry[] = []
    const running: Promise<void>[] = []
    const released = new AbortController()
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

        const due = async (): Promise<boolean> => {
            if (entry.at !== undefined) {
                await sleep(durationMs(entry.at), undefined, { signal: released.signal }).catch(() => undefined)
                return true
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

        if (!(await due()) || released.signal.aborted) {
            record.error = entry.when
                ? withProbeFailure(
                      `never applied: running_on_queue ${entry.when.params.queue} at least ${entry.when.params.atLeast} did not hold before the drive ended`
                  )
                : 'never applied: released before its offset'
            return
        }
        const definition = VALVES.find(({ name }) => name === entry.valve)!
        const holdEndsAt = Date.now() + durationMs(entry.for)
        const held = AbortSignal.any([released.signal, AbortSignal.timeout(durationMs(entry.for))])
        let actuation: Actuation | undefined
        try {
            actuation = await definition.apply(
                { ...context, pollMs, faultObservedWithinMs, signal: held },
                entry.target,
                entry.dose
            )
            record.appliedAt = now()
            if (!(await actuation.observed())) {
                record.error = 'applied but not observed'
            } else if (entry.when && (await runningJobs(entry.when.params.queue)) < entry.when.params.atLeast) {
                record.error = withProbeFailure(
                    `applied after running_on_queue ${entry.when.params.queue} at least ${entry.when.params.atLeast} stopped holding`
                )
            } else {
                record.observedAt = now()
            }
            await sleep(Math.max(0, holdEndsAt - Date.now()), undefined, { signal: released.signal }).catch(
                () => undefined
            )
        } catch (error) {
            record.error = (error as Error).message
        } finally {
            if (actuation) {
                try {
                    await actuation.release()
                    record.releasedAt = now()
                } catch (error) {
                    record.error = (error as Error).message
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
    }
}
