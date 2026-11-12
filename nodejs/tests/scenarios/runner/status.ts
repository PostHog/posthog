import type { RoleExit } from '../environment/supervisor'
import type { DriveSummary } from '../generator/generator'
import type { Convergence, InvariantResult } from '../judge/judge'
import type { ValveTimelineEntry } from '../valves/valves'

export type Status = 'passed' | 'failed' | 'invalid'

export const EXIT_CODE = { passed: 0, failed: 1, invalid: 2, writeFailed: 3 } as const

export function exitCodeOf({ status, scorecardError }: { status: Status; scorecardError?: string }): number {
    return scorecardError === undefined ? EXIT_CODE[status] : EXIT_CODE.writeFailed
}

export type Verdict = {
    minOffered: number
    units: DriveSummary
    down: string[]
    convergence: Convergence
    invariants: InvariantResult[]
    timeline: ValveTimelineEntry[]
    exits: RoleExit[]
}

const appliedDuring = (entry: ValveTimelineEntry, at: string): boolean =>
    entry.appliedAt !== undefined && entry.appliedAt <= at && (entry.releasedAt === undefined || at <= entry.releasedAt)

function unexpectedExit({ role, at, code, signal }: RoleExit, timeline: ValveTimelineEntry[]): string {
    const applied = timeline.filter((entry) => entry.target === role && appliedDuring(entry, at))
    return [
        `${role} exited (${signal ?? `code ${code}`}) without a valve causing it`,
        ...applied.map(({ valve, target }) => `while ${valve} on ${target} was applied`),
    ].join(', ')
}

export function statusOf({ minOffered, units, down, convergence, invariants, timeline, exits }: Verdict): {
    status: Status
    statusReason: string
} {
    if (down.length > 0) {
        return { status: 'invalid', statusReason: `dependencies went away: ${down.join(', ')}` }
    }
    if (units.targetUnits === 0 || units.offeredUnits < minOffered * units.targetUnits) {
        return {
            status: 'invalid',
            statusReason: `the generator offered ${units.offeredUnits} of ${units.targetUnits} units, under minOffered ${minOffered}`,
        }
    }
    const crashes = exits.filter(({ byValve }) => !byValve).map((exit) => unexpectedExit(exit, timeline))
    const unobserved = timeline
        .filter(({ observedAt }) => observedAt === undefined)
        .map(({ valve, target, error }) => `${valve} on ${target} was not observed: ${error ?? 'no record'}`)
    const failures = [
        ...(convergence.converged
            ? []
            : [
                  `not converged: ${convergence.unfinishedJobs} unfinished jobs, ${convergence.unrecorded.length} units without a delivery record`,
              ]),
        ...invariants
            .filter(({ passed }) => !passed)
            .map(({ name, violation }) => `${name} failed${violation ? `: ${violation}` : ''}`),
    ]
    if (crashes.length === 0 && failures.length === 0 && unobserved.length > 0) {
        return { status: 'invalid', statusReason: unobserved.join('; ') }
    }
    const reasons = [...crashes, ...unobserved, ...failures]
    return reasons.length > 0
        ? { status: 'failed', statusReason: reasons.join('; ') }
        : { status: 'passed', statusReason: 'every invariant held' }
}
