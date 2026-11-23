import type { Named, Step } from '../cards'
import type { Profile } from '../cards/schema'
import { pause } from '../duration'
import type { DrivenStep, StepGate, StepWindow } from '../generator/generator'
import { type Admission, admissionsOf } from '../runner/status'
import { BarResult, WriterCpu, judgeStep, unsourced } from './bars'
import { type DeliveryEvidence, acceptedDeliveriesOf, missedDeliveriesOf, refusalsOf } from './invariants'
import type { Convergence, InvariantResult, JournalEntry } from './judge'
import {
    type DriveWindow,
    type HostSample,
    type MetricSample,
    type QueueSample,
    SCRAPE_GAP_MS,
    baselineOf,
} from './measurements'

export type RampEnd = 'broke' | 'ceiling' | 'harness_limit'

export type BreakKind = 'bar' | 'gate' | 'invariant' | 'harness'

type BrokeAt = {
    scale: number | null
    offeredPerSecond: number | null
    at: string | null
    part: string | null
}

export type Broke = BrokeAt &
    ({ kind: 'harness'; by: HarnessPart } | { kind: Exclude<BreakKind, 'harness'>; by: string })

type HarnessPart = 'generator' | 'runner' | 'run_host' | 'target'

export type RampStop = { index: number; end: Exclude<RampEnd, 'ceiling'>; reason: string; broke?: Broke }

export type HardFailure = 'intake_refused' | 'step_loss' | 'backlog_undrained' | 'harness_limit'

export type HardStop = { failure: HardFailure; scale: number | null; reason: string }

export type StepRates = {
    index: number
    scale: number
    expected: number
    lost: number | null
    lossRate: number | null
    sent: number
    duplicates: number | null
    duplicateRate: number | null
    refused: number
    refusedRate: number | null
}

export type Ramp = {
    end: RampEnd
    sustainedScale: number | null
    broke?: Broke
    reason: string
    stop?: HardStop
    rates?: StepRates[]
}

export const STEP_LOSS_LIMIT = 0.05

const AT_LEAST_ONCE = 'at_least_once'

export type LiveRamp = {
    minOffered: number
    bars: Named[]
    gates: Record<string, number>
    judgesRefusals: boolean
    driveStartedAt: number
    hostCpuCeiling?: number
    profile: Pick<Profile, 'load' | 'host'>
    journal(): readonly JournalEntry[]
    samples(): readonly MetricSample[]
    queue(): readonly QueueSample[]
    host(): readonly HostSample[]
    writerCpu(window: DriveWindow): Promise<WriterCpu>
    targetLimit?(window: StepWindow): Promise<string | undefined>
}

export type RampWatch = {
    record(entry: JournalEntry): void
    gate: StepGate
    halt: AbortSignal
    stopped(): RampStop | undefined
    settled(): ReadonlyMap<number, readonly BarResult[]>
    pending(): Promise<void>
}

const REFUSED_AT_INTAKE = 'refused_at_intake'
const WRITER_CPU_UNDER = 'writer_cpu_under'

const iso = (at: number): string => new Date(at).toISOString()

const percentOf = (share: number): string => `${Number((share * 100).toFixed(2))}%`

const rateOf = (count: number | null, of: number): number | null => (count === null || of === 0 ? null : count / of)

export function stepRatesOf(
    steps: readonly Pick<DrivenStep, 'index' | 'scale'>[],
    evidence: DeliveryEvidence,
    judged: { lost: boolean; duplicates: boolean },
    { unfinishedJobs }: Pick<Convergence, 'unfinishedJobs'>
): StepRates[] {
    const lossSettled = judged.lost && unfinishedJobs === 0
    const stepOf = new Map(evidence.journal.map(({ unitId, step }) => [unitId, step]))
    const countBy = <T>(items: readonly T[], step: (item: T) => number | undefined, by: (item: T) => number) => {
        const counts = new Map<number | undefined, number>()
        items.forEach((item) => counts.set(step(item), (counts.get(step(item)) ?? 0) + by(item)))
        return counts
    }
    const expected = countBy(
        evidence.journal.filter(({ answer }) => answer.accepted),
        ({ step }) => step,
        ({ expect }) => expect.deliveries.length
    )
    const lost = countBy(
        missedDeliveriesOf(evidence),
        ({ unitId }) => stepOf.get(unitId),
        () => 1
    )
    const accepted = acceptedDeliveriesOf(evidence.truth)
    const sent = countBy(
        accepted,
        ({ record }) => stepOf.get(record.unitId),
        () => 1
    )
    const duplicates = countBy(
        accepted,
        ({ record }) => stepOf.get(record.unitId),
        ({ accepted }) => accepted - 1
    )
    const offeredToIntake = countBy(
        evidence.journal.filter(({ kind }) => kind !== 'event'),
        ({ step }) => step,
        () => 1
    )
    const refused = countBy(
        refusalsOf(evidence.journal),
        ({ step }) => step,
        () => 1
    )
    return steps.map(({ index, scale }) => {
        const due = expected.get(index) ?? 0
        const delivered = sent.get(index) ?? 0
        const missed = lossSettled ? (lost.get(index) ?? 0) : null
        const extra = judged.duplicates ? (duplicates.get(index) ?? 0) : null
        return {
            index,
            scale,
            expected: due,
            lost: missed,
            lossRate: rateOf(missed, due),
            sent: delivered,
            duplicates: extra,
            duplicateRate: rateOf(extra, delivered),
            refused: refused.get(index) ?? 0,
            refusedRate: rateOf(refused.get(index) ?? 0, offeredToIntake.get(index) ?? 0),
        }
    })
}

const lossOf = (lost: number, { expected, scale }: StepRates): string =>
    `${lost} of ${expected} deliveries were lost in the ${scale}x step (${percentOf(lost / expected)}), over the ${percentOf(STEP_LOSS_LIMIT)} hard limit`

const recordedOf = (
    rates: readonly StepRates[],
    count: (step: StepRates) => number | null,
    of: (step: StepRates) => number,
    what: (count: number, of: number) => string
): string | undefined => {
    const total = rates.reduce((sum, step) => sum + (count(step) ?? 0), 0)
    if (total === 0) {
        return undefined
    }
    const all = rates.reduce((sum, step) => sum + of(step), 0)
    const steps = rates.flatMap((step) => (count(step) ? [`${count(step)} in the ${step.scale}x step`] : []))
    return `${what(total, all)} (${percentOf(total / all)}): ${steps.join(', ')}`
}

export function ratesReasonOf(rates: readonly StepRates[], failed: { lost: boolean; duplicates: boolean }): string[] {
    return [
        failed.lost
            ? recordedOf(
                  rates,
                  ({ lost }) => lost,
                  ({ expected }) => expected,
                  (lost, expected) => `lost ${lost} of ${expected} deliveries`
              )
            : undefined,
        failed.duplicates
            ? recordedOf(
                  rates,
                  ({ duplicates }) => duplicates,
                  ({ sent }) => sent,
                  (duplicates, sent) =>
                      `sent ${duplicates} duplicate${duplicates === 1 ? '' : 's'} of ${sent} deliveries`
              )
            : undefined,
    ].filter((reason): reason is string => reason !== undefined)
}

const kindOf = (name: string, gates: Record<string, number>): 'gate' | 'invariant' =>
    gates[name] === undefined ? 'invariant' : 'gate'

const perSecond = (units: number, { startedAt, endedAt }: Pick<DrivenStep, 'startedAt' | 'endedAt'>): number =>
    endedAt > startedAt ? units / ((endedAt - startedAt) / 1000) : 0

const shortfallOf = (step: DrivenStep, minOffered: number): string | undefined =>
    step.dueUnits === 0
        ? `the generator had no units to offer in the ${step.scale}x step`
        : step.offeredUnits / step.dueUnits < minOffered
          ? `the generator offered ${step.offeredUnits} of ${step.dueUnits} units in the ${step.scale}x step, under minOffered ${minOffered}`
          : undefined

// The runner process also hosts the provider edge, so a busy event loop answers webhooks late and slows the workers
// that wait on them. Host CPU cannot see one saturated core, and a late edge would otherwise read as a product break.
const MAX_LOOP_LAG_P99_MS = 250

const laggedOf = ({ loopLagP99Ms, scale }: Pick<DrivenStep, 'loopLagP99Ms' | 'scale'>): string | undefined =>
    loopLagP99Ms !== undefined && loopLagP99Ms > MAX_LOOP_LAG_P99_MS
        ? `the runner's event loop lagged ${loopLagP99Ms} ms at p99 in the ${scale}x step, over ${MAX_LOOP_LAG_P99_MS} ms`
        : undefined

const harness = (step: DrivenStep, by: HarnessPart): Broke => ({
    scale: step.scale,
    offeredPerSecond: perSecond(step.offeredUnits, step),
    by,
    kind: 'harness',
    at: iso(step.startedAt),
    part: null,
})

const admissionLimitOf = (admissions: readonly Admission[], step: DrivenStep): Omit<RampStop, 'index'> | undefined => {
    const refused = admissions.find(({ passed }) => !passed)
    return (
        refused && {
            end: 'harness_limit',
            reason: `the ${refused.name} admission failed at the ${step.scale}x step: ${refused.reason}`,
            broke: harness(step, refused.name === 'host' ? 'run_host' : 'generator'),
        }
    )
}

type LiveVerdict = { results?: BarResult[]; stop?: Omit<RampStop, 'index'> }

async function judgeLive(live: LiveRamp, window: StepWindow, offered: number): Promise<LiveVerdict> {
    const step = { ...window, offeredUnits: offered }
    const lagged = laggedOf(step)
    if (lagged) {
        return { stop: { end: 'harness_limit', reason: lagged, broke: harness(step, 'runner') } }
    }
    const shortfall = shortfallOf(step, live.minOffered)
    if (shortfall) {
        return { stop: { end: 'harness_limit', reason: shortfall, broke: harness(step, 'generator') } }
    }
    const limited = await live.targetLimit?.(window)
    if (limited) {
        return { stop: { end: 'harness_limit', reason: limited, broke: harness(step, 'target') } }
    }
    const span = { startedAt: step.startedAt, endedAt: step.endedAt }
    const admitted =
        step.index === 0
            ? admissionLimitOf(
                  admissionsOf(
                      live.profile,
                      baselineOf({
                          samples: [...live.samples()],
                          queue: [...live.queue()],
                          host: [...live.host()],
                          drive: span,
                          timeline: [],
                      }),
                      step.scale
                  ),
                  step
              )
            : undefined
    if (admitted) {
        return { stop: admitted }
    }
    const writerCpu = live.bars.some(({ name }) => name === WRITER_CPU_UNDER)
        ? await live.writerCpu(span).catch((error: unknown) => ({ unread: messageOf(error) }))
        : []
    const results = judgeStep(
        live.bars,
        {
            journal: live.journal(),
            samples: live.samples(),
            host: live.host(),
            steps: [
                {
                    scale: step.scale,
                    fromMs: step.startedAt - live.driveStartedAt,
                    toMs: step.endedAt - live.driveStartedAt,
                    offeredUnits: offered,
                },
            ],
            drive: { startedAt: live.driveStartedAt, endedAt: step.endedAt },
            writerCpu,
            hostCpuCeiling: live.hostCpuCeiling,
        },
        0
    )
    const unjudged = results.find(({ harnessLimit }) => harnessLimit !== undefined)
    return {
        results,
        ...(unjudged && {
            stop: {
                end: 'harness_limit',
                reason: `${unjudged.name} was not judged: ${unjudged.unjudged}`,
                broke: harness(step, unjudged.harnessLimit!.by),
            },
        }),
    }
}

const offeredBefore = (entry: JournalEntry, kept: JournalEntry): boolean =>
    entry.offeredAt - kept.offeredAt < 0 || (entry.offeredAt === kept.offeredAt && (entry.step ?? 0) < (kept.step ?? 0))

const insertionOf = (kept: readonly JournalEntry[], entry: JournalEntry): number => {
    let low = 0
    let high = kept.length
    while (low < high) {
        const middle = (low + high) >> 1
        if (offeredBefore(entry, kept[middle])) {
            high = middle
        } else {
            low = middle + 1
        }
    }
    return low
}

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

export function watchRamp(live: LiveRamp, signal: AbortSignal): RampWatch {
    const halt = new AbortController()
    const earliestRefused: JournalEntry[] = []
    let refusedCount = 0
    const settled = new Map<number, readonly BarResult[]>()
    const gate = live.gates[REFUSED_AT_INTAKE] ?? 0
    const crossingAt = Math.max(0, Math.floor(gate))
    let stop: RampStop | undefined
    const judging: Promise<void>[] = []

    const stopWith = (stopped: RampStop): void => {
        if (stop === undefined || stopped.index < stop.index) {
            stop = stopped
        }
        halt.abort()
    }

    return {
        halt: halt.signal,
        stopped: () => stop,
        settled: () => settled,
        pending: async () => {
            await Promise.all(judging)
        },
        record: (entry) => {
            if (signal.aborted || !live.judgesRefusals || refusalsOf([entry]).length === 0) {
                return
            }
            refusedCount += 1
            const at = insertionOf(earliestRefused, entry)
            if (at > crossingAt) {
                return
            }
            earliestRefused.splice(at, 0, entry)
            earliestRefused.length = Math.min(earliestRefused.length, crossingAt + 1)
            const index = earliestRefused[crossingAt]?.step
            if (index !== undefined) {
                stopWith({
                    index,
                    end: 'broke',
                    reason: `${REFUSED_AT_INTAKE} went over its gate of ${gate} with ${refusedCount} refused`,
                })
            }
        },
        gate: (window, offered) => {
            const judged = judgeGate(window, offered)
            judging.push(judged)
            return judged
        },
    }

    async function judgeGate(window: StepWindow, offered: () => number): Promise<void> {
        try {
            await pause(window.endedAt + SCRAPE_GAP_MS - Date.now(), signal)
            if (signal.aborted) {
                return
            }
            const { results, stop: stopped } = await judgeLive(live, window, offered())
            if (signal.aborted) {
                return
            }
            if (results) {
                settled.set(window.index, results)
            }
            if (stopped) {
                stopWith({ index: window.index, ...stopped })
            }
        } catch (error) {
            if (signal.aborted) {
                return
            }
            stopWith({
                index: window.index,
                end: 'harness_limit',
                reason: `the live judge failed at the ${window.scale}x step: ${messageOf(error)}`,
                broke: harness({ ...window, offeredUnits: offered() }, 'run_host'),
            })
        }
    }
}

export type RampEvidence = {
    planned: readonly Step[]
    steps: readonly DrivenStep[]
    minOffered: number
    stop: RampStop | undefined
    bars: readonly BarResult[]
    invariants: readonly InvariantResult[]
    gates: Record<string, number>
    journal: readonly JournalEntry[]
    admissions: readonly Admission[]
    convergence: Pick<Convergence, 'converged' | 'unfinishedJobs'>
    rates?: readonly StepRates[]
}

type Candidate = { index: number; rank: number; broke: Broke; reason: string; hard?: HardFailure }

const RANK = { generator: 0, runner: 0, bar: 1, gate: 2, invariant: 2, run_host: 3, target: 3 } as const

const rankOf = (broke: Broke): number => (broke.kind === 'harness' ? RANK[broke.by] : RANK[broke.kind])

function candidatesOf({ planned, steps, minOffered, stop, bars, invariants, gates, journal, rates }: RampEvidence): {
    placed: Candidate[]
    unplaced: Broke[]
} {
    const indexOfScale = (scale: number): number => steps.findIndex((step) => step.scale === scale)
    const placed: Candidate[] = []
    const add = (index: number, broke: Broke, reason: string, hard?: HardFailure): void => {
        if (index >= 0 && index < steps.length) {
            placed.push({ index, rank: rankOf(broke), broke, reason, ...(hard && { hard }) })
        }
    }
    const cutShort = (step: DrivenStep): boolean =>
        stop !== undefined &&
        step.index === steps.length - 1 &&
        step.endedAt - step.startedAt < planned[step.index].toMs - planned[step.index].fromMs
    for (const step of steps) {
        const lagged = laggedOf(step)
        if (lagged) {
            add(step.index, harness(step, 'runner'), lagged)
        }
        const shortfall = shortfallOf(step, minOffered)
        if (shortfall && !cutShort(step)) {
            add(step.index, harness(step, 'generator'), shortfall)
        }
    }
    const stopped = stop && steps[stop.index]
    if (stop?.broke && stopped) {
        add(stop.index, { ...stop.broke, offeredPerSecond: perSecond(stopped.offeredUnits, stopped) }, stop.reason)
    }
    for (const { name, unjudged, harnessLimit, breakingPoint } of bars) {
        const broken = breakingPoint && steps[indexOfScale(breakingPoint.scale)]
        if (breakingPoint && broken) {
            const { scale, at, part } = breakingPoint
            add(
                broken.index,
                { scale, offeredPerSecond: perSecond(broken.offeredUnits, broken), by: name, kind: 'bar', at, part },
                `${name} broke at the ${scale}x step`
            )
        }
        if (harnessLimit) {
            const index = indexOfScale(harnessLimit.scale)
            if (index >= 0) {
                add(index, harness(steps[index], harnessLimit.by), `${name} was not judged: ${unjudged}`)
            }
        }
    }
    const judgesLoss = invariants.some(({ name }) => name === AT_LEAST_ONCE)
    for (const rated of rates ?? []) {
        const step = steps[rated.index]
        if (judgesLoss && step && rated.lost !== null && rated.lossRate !== null && rated.lossRate > STEP_LOSS_LIMIT) {
            add(
                step.index,
                {
                    scale: step.scale,
                    offeredPerSecond: perSecond(step.offeredUnits, step),
                    by: AT_LEAST_ONCE,
                    kind: 'invariant',
                    at: iso(step.startedAt),
                    part: null,
                },
                lossOf(rated.lost, rated),
                'step_loss'
            )
        }
    }
    const stepOf = new Map(journal.map(({ unitId, step }) => [unitId, step]))
    const unplaced: Broke[] = []
    for (const { name, passed, crossedBy } of invariants) {
        if (passed || name !== REFUSED_AT_INTAKE) {
            continue
        }
        const kind = kindOf(name, gates)
        const index = crossedBy === undefined ? undefined : stepOf.get(crossedBy)
        const step = index === undefined ? undefined : steps[index]
        if (step === undefined) {
            unplaced.push({ scale: null, offeredPerSecond: null, by: name, kind, at: null, part: null })
            continue
        }
        add(
            step.index,
            {
                scale: step.scale,
                offeredPerSecond: perSecond(step.offeredUnits, step),
                by: name,
                kind,
                at: iso(step.startedAt),
                part: null,
            },
            `${name} broke at the ${step.scale}x step`,
            'intake_refused'
        )
    }
    return { placed, unplaced }
}

export function rampOf(evidence: RampEvidence): Ramp {
    const { placed, unplaced } = candidatesOf(evidence)
    placed.sort((a, b) => a.index - b.index || a.rank - b.rank)
    const [hard] = placed.filter(({ broke, hard }) => hard !== undefined || broke.kind === 'harness')
    const { unfinishedJobs, converged } = evidence.convergence
    const backlog =
        converged || !unfinishedJobs
            ? undefined
            : `the backlog did not drain within convergeWithin: ${unfinishedJobs} job${unfinishedJobs === 1 ? '' : 's'} stayed unfinished`
    const ramp = endOf(evidence, placed, unplaced, backlog)
    const stop: HardStop | undefined =
        ramp.end === 'harness_limit'
            ? { failure: 'harness_limit', scale: ramp.broke?.scale ?? null, reason: ramp.reason }
            : hard !== undefined
              ? { failure: hard.hard ?? 'harness_limit', scale: hard.broke.scale, reason: hard.reason }
              : unplaced.length > 0
                ? { failure: 'intake_refused', scale: null, reason: ramp.reason }
                : backlog === undefined
                  ? undefined
                  : { failure: 'backlog_undrained', scale: null, reason: backlog }
    return { ...ramp, ...(stop && { stop }), ...(evidence.rates && { rates: [...evidence.rates] }) }
}

function endOf(evidence: RampEvidence, placed: Candidate[], unplaced: Broke[], backlog: string | undefined): Ramp {
    const { planned, steps, admissions } = evidence
    const sustainedBefore = (index: number): number | null =>
        index > 0 && unplaced.length === 0 ? steps[index - 1].scale : null
    // A lagging runner offers less than it planned, so a failed admission at its first step names the runner's limit.
    const admitted = steps[0] && !laggedOf(steps[0]) && admissionLimitOf(admissions, steps[0])
    if (admitted) {
        return { end: 'harness_limit', sustainedScale: null, broke: admitted.broke, reason: admitted.reason }
    }
    const last = steps.at(-1)
    const interrupted: Ramp | undefined =
        last && last.endedAt - last.startedAt < planned[last.index].toMs - planned[last.index].fromMs
            ? {
                  end: 'harness_limit',
                  sustainedScale: sustainedBefore(last.index),
                  broke: harness(last, 'generator'),
                  reason: `the drive ended during the ${last.scale}x step`,
              }
            : undefined
    const [first] = placed
    if (interrupted && first?.index === last?.index && first.broke.kind === 'harness' && first.broke.by !== 'runner') {
        return interrupted
    }
    if (first) {
        return {
            end: first.broke.kind === 'harness' ? 'harness_limit' : 'broke',
            sustainedScale: sustainedBefore(first.index),
            broke: first.broke,
            reason: first.reason,
        }
    }
    const [orphan] = unplaced
    if (orphan) {
        return {
            end: 'broke',
            sustainedScale: null,
            broke: orphan,
            reason: `${orphan.by} failed, and the unit that crossed its gate falls in no step`,
        }
    }
    if (interrupted) {
        return interrupted
    }
    if (steps.length < planned.length) {
        const { scale } = planned[steps.length]
        return {
            end: 'harness_limit',
            sustainedScale: steps.at(-1)?.scale ?? null,
            broke: { scale, offeredPerSecond: 0, by: 'generator', kind: 'harness', at: null, part: null },
            reason: `the drive ended before the ${scale}x step`,
        }
    }
    if (backlog !== undefined) {
        return {
            end: 'broke',
            sustainedScale: null,
            broke: { scale: null, offeredPerSecond: null, by: 'convergence', kind: 'invariant', at: null, part: null },
            reason: backlog,
        }
    }
    const ceiling = planned[planned.length - 1].scale
    const notJudged = evidence.bars.filter(unsourced).map(({ name, unjudged }) => `${name} was not judged: ${unjudged}`)
    return {
        end: 'ceiling',
        sustainedScale: ceiling,
        reason:
            notJudged.length === 0
                ? `every step held up to the ${ceiling}x ceiling`
                : [`every judged bar held up to the ${ceiling}x ceiling`, ...notJudged].join('; '),
    }
}
