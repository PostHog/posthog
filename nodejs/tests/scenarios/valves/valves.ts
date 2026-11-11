import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import type { Definition } from '../cards/definitions'
import { CdpRole, ValveEntry } from '../cards/schema'
import { durationMs } from '../duration'
import type { Actuation, Environment } from '../environment/environment'
import type { CyclotronProbe } from '../probe/cyclotron-probe'

export type ValveContext = {
    environment: Pick<Environment, 'actuate'>
    probe: Pick<CyclotronProbe, 'runningJobs'>
    teams: number[]
}

export type ValveDefinition = Definition & {
    target: z.ZodType<string>
    apply(context: ValveContext, target: string, dose: unknown): Promise<Actuation>
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

export const VALVES: ValveDefinition[] = [roleKill]

const POLL_MS = 1000

const now = (): string => new Date().toISOString()

export function createValves({ pollMs = POLL_MS, definitions = VALVES } = {}): Valves {
    const entries: ValveTimelineEntry[] = []
    const running: Promise<void>[] = []
    const released = new AbortController()
    let releasing: Promise<void> | undefined

    const scheduled = async (entry: ValveEntry, context: ValveContext): Promise<boolean> => {
        if (entry.at !== undefined) {
            await sleep(durationMs(entry.at), undefined, { signal: released.signal }).catch(() => undefined)
            return true
        }
        const { queue, atLeast } = entry.when!.params
        while (!released.signal.aborted) {
            const jobs = await context.probe.runningJobs({ teams: context.teams, queues: [queue] }).catch(() => 0)
            if (jobs >= atLeast) {
                return true
            }
            await sleep(pollMs, undefined, { signal: released.signal }).catch(() => undefined)
        }
        return false
    }

    const run = async (entry: ValveEntry, context: ValveContext, record: ValveTimelineEntry): Promise<void> => {
        if (!(await scheduled(entry, context)) || released.signal.aborted) {
            const { queue, atLeast } = entry.when?.params ?? {}
            record.error = entry.when
                ? `never applied: running_on_queue ${queue} at least ${atLeast} did not hold before the drive ended`
                : 'never applied: released before its offset'
            return
        }
        const definition = definitions.find(({ name }) => name === entry.valve)!
        let actuation: Actuation | undefined
        try {
            record.appliedAt = now()
            actuation = await definition.apply(context, entry.target, entry.dose)
            if (await actuation.observed()) {
                record.observedAt = now()
            } else {
                record.error = 'applied but not observed'
            }
            await sleep(durationMs(entry.for), undefined, { signal: released.signal }).catch(() => undefined)
        } catch (error) {
            record.error = (error as Error).message
        } finally {
            if (actuation) {
                await actuation.release()
                record.releasedAt = now()
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
