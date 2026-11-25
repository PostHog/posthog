import type { Profile } from '../cards/schema'
import { nameOf } from '../environment/identity'
import type { RoleExit } from '../environment/supervisor'
import type { DriveSummary } from '../generator/generator'
import { BarResult, unsourced } from '../judge/bars'
import { atLeastOnce, bouncedSuppressed, noLoss } from '../judge/invariants'
import type { Convergence, InvariantResult } from '../judge/judge'
import { Baseline, DriveWindow, MIN_BASELINE_SECONDS } from '../judge/measurements'
import { type Ramp, ratesReasonOf } from '../judge/ramp'
import type { WriterSample } from '../probe/writer-probe'
import { VALVES, ValveTimelineEntry } from '../valves/valves'
import { DependencyLoss, dependencyReasonOf } from './dependency-watch'

export type Status = 'passed' | 'failed' | 'invalid'

export const EXIT_CODE = { passed: 0, failed: 1, invalid: 2, writeFailed: 3 } as const

export function exitCodeOf({ status, scorecardError }: { status: Status; scorecardError?: string }): number {
    return scorecardError === undefined ? EXIT_CODE[status] : EXIT_CODE.writeFailed
}

export type Admission = { name: 'load' | 'host'; passed: boolean; reason: string }

type RateCheck = { what: string; measured: number | undefined; target: number }

const percent = (share: number): string => `${Number((share * 100).toFixed(1))}%`
const rate = (perSecond: number): string => `${Number(perSecond.toFixed(2))}/s`

// A profile measures its load targets at 1x, and a ramp that opens higher drives that many times the load.
export function admissionsOf(
    { load, host }: Pick<Profile, 'load' | 'host'>,
    baseline: Baseline,
    openingScale = 1
): Admission[] {
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
                target: target * openingScale,
            })),
            ...(targets.newJobsPerSecond === undefined
                ? []
                : [
                      {
                          what: 'new jobs',
                          measured: baseline.newJobsPerSecond,
                          target: targets.newJobsPerSecond * openingScale,
                      },
                  ]),
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
    units: Pick<DriveSummary, 'targetUnits' | 'offeredUnits' | 'steps'>
    down: DependencyLoss[]
    convergence: Convergence
    invariants: InvariantResult[]
    timeline: ValveTimelineEntry[]
    exits: RoleExit[]
    writer: readonly WriterSample[]
    drive: DriveWindow
    bars: BarResult[]
    ramp?: Ramp
}

const DATABASE_TARGETS = new Set(['postgres', 'cyclotron'])
const SUSTAINED_FAILURES = 5
const CONNECTION_LOST = /^(08...|57P01)$/

const appliedWithin = (
    { intentAt, appliedAt, releasedAt }: ValveTimelineEntry,
    at: string,
    graceMs: number
): boolean => {
    const from = intentAt ?? appliedAt
    const time = Date.parse(at)
    return (
        from !== undefined &&
        appliedAt !== undefined &&
        Date.parse(from) <= time &&
        (releasedAt === undefined || time <= Date.parse(releasedAt) + graceMs)
    )
}

const exitedByValve = (exit: RoleExit, timeline: ValveTimelineEntry[]): boolean =>
    exit.byValve ||
    (exit.code !== null &&
        exit.code < 128 &&
        exit.signal === null &&
        timeline.some((entry) => {
            const valve = VALVES.find(({ name }) => name === entry.valve)
            return (
                valve?.roleExitGraceMs !== undefined &&
                (valve.restarts?.includes(exit.role) ?? true) &&
                appliedWithin(entry, exit.at, valve.roleExitGraceMs)
            )
        }))

function unexpectedExit(exit: RoleExit, timeline: ValveTimelineEntry[]): string {
    const applied = timeline.filter((entry) => DATABASE_TARGETS.has(entry.target) && appliedWithin(entry, exit.at, 0))
    return [
        `${nameOf(exit)} exited (${exit.signal ?? `code ${exit.code}`}) without a valve causing it`,
        ...applied.map(({ valve, target }) => `while ${valve} on ${target} was applied`),
    ].join(', ')
}

function interruptionWithoutValve(
    writer: readonly WriterSample[],
    drive: DriveWindow,
    timeline: ValveTimelineEntry[]
): string | undefined {
    const intents = timeline.flatMap(({ intentAt }) => (intentAt === undefined ? [] : [Date.parse(intentAt)]))
    const firstIntent = intents.length === 0 ? drive.endedAt : Math.max(Math.min(...intents), drive.startedAt)
    const lastRelease = Math.max(
        drive.endedAt,
        ...timeline.flatMap(({ releasedAt }) => (releasedAt === undefined ? [] : [Date.parse(releasedAt)]))
    )
    const anyValve = timeline.some(({ intentAt, appliedAt }) => (intentAt ?? appliedAt) !== undefined)
    let failedInARow = 0
    for (const sample of [...writer].sort((a, b) => a.at - b.at)) {
        const unguarded = !anyValve || sample.at + sample.latencyMs < firstIntent || sample.at >= lastRelease
        failedInARow = unguarded && !sample.ok ? failedInARow + 1 : 0
        if (failedInARow >= SUSTAINED_FAILURES || (unguarded && CONNECTION_LOST.test(sample.sqlstate ?? ''))) {
            const what =
                failedInARow >= SUSTAINED_FAILURES
                    ? `${SUSTAINED_FAILURES} writer probes failed in a row`
                    : `a writer probe lost its connection (SQLSTATE ${sample.sqlstate})`
            const when = !anyValve
                ? 'with no valve applied'
                : sample.at < firstIntent
                  ? 'before any valve applied'
                  : 'after the drive and every valve ended'
            return `Cyclotron interrupted without a valve: ${what} ${when}, at ${new Date(sample.at).toISOString()}`
        }
    }
    return undefined
}

const unreadReasonOf = (unread: string): string => `the judge could not read the final state: ${unread}`

export const unobservedReasonOf = ({ valve, target, error }: ValveTimelineEntry): string =>
    `${valve} on ${target} was not observed: ${error ?? 'no record'}`

export const unobservedValvesOf = (timeline: readonly ValveTimelineEntry[], drive: DriveWindow): string[] =>
    timeline.flatMap((entry) =>
        entry.observedAt === undefined
            ? [unobservedReasonOf(entry)]
            : entry.intentAt !== undefined && Date.parse(entry.intentAt) >= drive.endedAt
              ? [unobservedReasonOf({ ...entry, error: 'applied after the drive ended' })]
              : []
    )

const CHECKS_OF_SETTLED_DELIVERIES = new Set([atLeastOnce.name, bouncedSuppressed.name, noLoss.name])

export const judgedInvariantsOf = (
    checked: InvariantResult[],
    { unfinishedJobs }: Pick<Convergence, 'unfinishedJobs'>
): InvariantResult[] =>
    unfinishedJobs === null ? checked.filter(({ name }) => !CHECKS_OF_SETTLED_DELIVERIES.has(name)) : checked

export function statusOf(verdict: Verdict): { status: Status; statusReason: string; restarts: RoleExit[] } {
    const { exits, timeline } = verdict
    return {
        ...judgedOf(verdict),
        restarts: exits.filter((exit) => !exit.byValve && exitedByValve(exit, timeline)),
    }
}

function withRamp(
    verdict: { status: Status; statusReason: string },
    ramp: Ramp
): { status: Status; statusReason: string } {
    if (verdict.status !== 'passed' || ramp.end === 'ceiling') {
        return verdict
    }
    return ramp.end === 'harness_limit'
        ? { status: 'invalid', statusReason: `the ramp hit a harness limit: ${ramp.reason}` }
        : {
              status: 'failed',
              statusReason: [
                  `the ramp broke: ${ramp.reason}`,
                  ...(ramp.stop && ramp.stop.reason !== ramp.reason ? [ramp.stop.reason] : []),
              ].join('; '),
          }
}

function judgedOf(verdict: Verdict): { status: Status; statusReason: string } {
    if (!verdict.ramp) {
        return unrampedStatusOf(verdict)
    }
    const { invariants, convergence, ramp } = verdict
    const failed = (name: string): boolean =>
        invariants.some((invariant) => invariant.name === name && !invariant.passed)
    const recorded = ratesReasonOf(ramp.rates ?? [], {
        lost: failed('at_least_once'),
        duplicates: failed('duplicate_sends'),
    })
    const { unread, ...read } = convergence
    const rampJudgesConvergence =
        convergence.unfinishedJobs !== 0 ||
        invariants.some(({ name, crossedBy }) => name === 'at_least_once' && crossedBy !== undefined)
    const unramped = withRamp(
        unrampedStatusOf({
            ...verdict,
            bars: [],
            invariants: invariants.filter(({ crossedBy }) => crossedBy === undefined),
            convergence: rampJudgesConvergence ? { ...read, converged: true } : read,
        }),
        ramp
    )
    const ramped =
        recorded.length === 0
            ? unramped
            : unramped.status === 'passed'
              ? { status: 'failed' as const, statusReason: `the ramp ran to its last step, but ${recorded.join('; ')}` }
              : { ...unramped, statusReason: [unramped.statusReason, ...recorded].join('; ') }
    const notJudged = [
        ...verdict.bars.filter(unsourced).map(({ name, unjudged }) => `${name} was not judged: ${unjudged}`),
        ...(unread === undefined ? [] : [unreadReasonOf(unread)]),
    ]
    if (notJudged.length === 0) {
        return ramped
    }
    return ramped.status === 'passed'
        ? { status: 'invalid', statusReason: notJudged.join('; ') }
        : { ...ramped, statusReason: [ramped.statusReason, ...notJudged].join('; ') }
}

const notConvergedOf = ({ converged, unfinishedJobs, unrecorded }: Convergence): string[] =>
    converged || unfinishedJobs === null
        ? []
        : [`not converged: ${unfinishedJobs} unfinished jobs, ${unrecorded.length} units without a delivery record`]

function unrampedStatusOf({
    admissions,
    minOffered,
    units,
    down,
    convergence,
    invariants,
    timeline,
    exits,
    writer,
    drive,
    bars,
    ramp,
}: Verdict): {
    status: Status
    statusReason: string
} {
    const lost = dependencyReasonOf(down, units.steps)
    if (lost !== undefined) {
        return { status: 'invalid', statusReason: lost }
    }
    const refused = admissions.filter(({ passed }) => !passed)
    if (refused.length > 0) {
        return {
            status: 'invalid',
            statusReason: refused.map(({ name, reason }) => `the ${name} admission failed: ${reason}`).join('; '),
        }
    }
    if (units.targetUnits === 0 || (!ramp && units.offeredUnits < minOffered * units.targetUnits)) {
        return {
            status: 'invalid',
            statusReason: `the generator offered ${units.offeredUnits} of ${units.targetUnits} units, under minOffered ${minOffered}`,
        }
    }
    const interrupted = interruptionWithoutValve(writer, drive, timeline)
    if (interrupted !== undefined) {
        return { status: 'invalid', statusReason: interrupted }
    }
    const crashes = exits.filter((exit) => !exitedByValve(exit, timeline)).map((exit) => unexpectedExit(exit, timeline))
    const valves = unobservedValvesOf(timeline, drive)
    const unjudgedOnlyByValves = valves.join('; ')
    const unobserved = [
        ...valves,
        ...invariants.flatMap(({ name, unjudged }) =>
            unjudged === undefined || unjudged === unjudgedOnlyByValves ? [] : [`${name} was not judged: ${unjudged}`]
        ),
        ...bars.flatMap(({ name, unjudged }) =>
            unjudged === undefined ? [] : [`${name} was not judged: ${unjudged}`]
        ),
        ...(convergence.unread === undefined ? [] : [unreadReasonOf(convergence.unread)]),
    ]
    const failures = [
        ...notConvergedOf(convergence),
        ...invariants
            .filter(({ passed, unjudged }) => !passed && unjudged === undefined)
            .map(({ name, violation }) => `${name} failed${violation ? `: ${violation}` : ''}`),
        ...bars.flatMap(({ name, unit, breakingPoint: broke }) =>
            broke === undefined
                ? []
                : [
                      `${name} broke at the ${broke.scale}x step, ${broke.offeredPerSecond.toFixed(1)} units/s offered: ${broke.key ? `${broke.key} ` : ''}${broke.value} ${unit}`,
                  ]
        ),
    ]
    if (crashes.length === 0 && failures.length === 0 && unobserved.length > 0) {
        return { status: 'invalid', statusReason: unobserved.join('; ') }
    }
    const unreleased = [
        ...timeline
            .filter(({ appliedAt, releasedAt }) => appliedAt !== undefined && releasedAt === undefined)
            .map(({ valve, target, error }) => `${valve} on ${target} was not released: ${error ?? 'no record'}`),
        ...timeline
            .filter(({ releaseError }) => releaseError !== undefined)
            .map(({ valve, target, releaseError }) => `${valve} on ${target} did not fail back: ${releaseError}`),
    ]
    if (unreleased.length > 0) {
        return { status: 'invalid', statusReason: unreleased.join('; ') }
    }
    const reasons = [...crashes, ...unobserved, ...failures]
    return reasons.length > 0
        ? { status: 'failed', statusReason: reasons.join('; ') }
        : { status: 'passed', statusReason: 'every invariant held' }
}
