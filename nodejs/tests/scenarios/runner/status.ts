import type { Profile } from '../cards/schema'
import { nameOf } from '../environment/identity'
import type { RoleExit } from '../environment/supervisor'
import type { DriveSummary } from '../generator/generator'
import type { Convergence, InvariantResult } from '../judge/judge'
import { Baseline, MIN_BASELINE_SECONDS } from '../judge/measurements'
import type { ValveTimelineEntry } from '../valves/valves'

export type Status = 'passed' | 'failed' | 'invalid'

export const EXIT_CODE = { passed: 0, failed: 1, invalid: 2, writeFailed: 3 } as const

export function exitCodeOf({ status, scorecardError }: { status: Status; scorecardError?: string }): number {
    return scorecardError === undefined ? EXIT_CODE[status] : EXIT_CODE.writeFailed
}

export type Admission = { name: 'load' | 'host'; passed: boolean; reason: string }

type RateCheck = { what: string; measured: number | undefined; target: number }

const percent = (share: number): string => `${Number((share * 100).toFixed(1))}%`
const rate = (perSecond: number): string => `${Number(perSecond.toFixed(2))}/s`

export function admissionsOf({ load, host }: Pick<Profile, 'load' | 'host'>, baseline: Baseline): Admission[] {
    const admissions: Admission[] = []
    const unmeasurable =
        baseline.seconds <= 0
            ? 'the drive had no baseline before its valve'
            : baseline.seconds >= MIN_BASELINE_SECONDS
              ? undefined
              : `the baseline was too short to measure: ${Number(baseline.seconds.toFixed(1))}s, under the ${MIN_BASELINE_SECONDS}s minimum`
    if (load) {
        const { targets, tolerance } = load
        const checks: RateCheck[] = [
            ...Object.entries(targets.claimsPerSecond).map(([queue, target]) => ({
                what: `${queue} claims`,
                measured: baseline.claimsPerSecond[queue] ?? 0,
                target,
            })),
            ...(targets.newJobsPerSecond === undefined
                ? []
                : [{ what: 'new jobs', measured: baseline.newJobsPerSecond, target: targets.newJobsPerSecond }]),
        ]
        const misses = checks
            .filter(
                ({ measured, target }) => measured === undefined || Math.abs(measured - target) > tolerance * target
            )
            .map(
                ({ what, measured, target }) =>
                    `${what} ${measured === undefined ? 'unmeasured' : rate(measured)}, not within ${percent(tolerance)} of ${rate(target)}`
            )
        const unscraped =
            Object.keys(targets.claimsPerSecond).length > 0 && baseline.scrapedSeconds < MIN_BASELINE_SECONDS
                ? `the role metrics covered ${Number(baseline.scrapedSeconds.toFixed(1))}s of the baseline, under the ${MIN_BASELINE_SECONDS}s minimum`
                : undefined
        admissions.push(
            unmeasurable !== undefined
                ? { name: 'load', passed: false, reason: unmeasurable }
                : unscraped !== undefined
                  ? { name: 'load', passed: false, reason: unscraped }
                  : misses.length > 0
                    ? { name: 'load', passed: false, reason: misses.join(', ') }
                    : {
                          name: 'load',
                          passed: true,
                          reason: `every baseline rate within ${percent(tolerance)} of its target`,
                      }
        )
    }
    if (host) {
        const { hostBusyShare } = baseline
        admissions.push(
            unmeasurable !== undefined
                ? { name: 'host', passed: false, reason: unmeasurable }
                : hostBusyShare === undefined
                  ? { name: 'host', passed: false, reason: 'no host CPU sample covers the baseline' }
                  : {
                        name: 'host',
                        passed: hostBusyShare < host.cpuCeiling,
                        reason: `host CPU ${percent(hostBusyShare)} busy in the baseline, ${hostBusyShare < host.cpuCeiling ? 'under' : 'over'} the ${percent(host.cpuCeiling)} ceiling`,
                    }
        )
    }
    return admissions
}

export type Verdict = {
    admissions: Admission[]
    minOffered: number
    units: DriveSummary
    down: string[]
    convergence: Convergence
    invariants: InvariantResult[]
    timeline: ValveTimelineEntry[]
    exits: RoleExit[]
}

const unexpectedExit = (exit: RoleExit): string =>
    `${nameOf(exit)} exited (${exit.signal ?? `code ${exit.code}`}) without a valve causing it`

export function statusOf({ admissions, minOffered, units, down, convergence, invariants, timeline, exits }: Verdict): {
    status: Status
    statusReason: string
} {
    if (down.length > 0) {
        return { status: 'invalid', statusReason: `dependencies went away: ${down.join(', ')}` }
    }
    const refused = admissions.filter(({ passed }) => !passed)
    if (refused.length > 0) {
        return {
            status: 'invalid',
            statusReason: refused.map(({ name, reason }) => `the ${name} admission failed: ${reason}`).join('; '),
        }
    }
    if (units.targetUnits === 0 || units.offeredUnits < minOffered * units.targetUnits) {
        return {
            status: 'invalid',
            statusReason: `the generator offered ${units.offeredUnits} of ${units.targetUnits} units, under minOffered ${minOffered}`,
        }
    }
    const crashes = exits.filter(({ byValve }) => !byValve).map(unexpectedExit)
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
    const unreleased = timeline.filter(
        ({ appliedAt, releasedAt }) => appliedAt !== undefined && releasedAt === undefined
    )
    if (unreleased.length > 0) {
        return {
            status: 'invalid',
            statusReason: unreleased
                .map(({ valve, target, error }) => `${valve} on ${target} was not released: ${error ?? 'no record'}`)
                .join('; '),
        }
    }
    const reasons = [...crashes, ...unobserved, ...failures]
    return reasons.length > 0
        ? { status: 'failed', statusReason: reasons.join('; ') }
        : { status: 'passed', statusReason: 'every invariant held' }
}
