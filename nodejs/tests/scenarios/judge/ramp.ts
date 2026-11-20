import type { Named, Step } from '../cards'
import type { Profile } from '../cards/schema'
import { pause } from '../duration'
import type { DrivenStep, StepGate, StepWindow } from '../generator/generator'
import { type Admission, admissionsOf } from '../runner/status'
import { BarResult, CpuPoint, judgeStep } from './bars'
import { crossedByOf, refusalsOf } from './invariants'
import type { InvariantResult, JournalEntry } from './judge'
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
    ({ kind: 'harness'; by: 'generator' | 'run_host' } | { kind: Exclude<BreakKind, 'harness'>; by: string })

export type RampStop = { index: number; end: Exclude<RampEnd, 'ceiling'>; reason: string; broke?: Broke }

export type Ramp = { end: RampEnd; sustainedScale: number | null; broke?: Broke; reason: string }

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
    writerCpu(window: DriveWindow): Promise<CpuPoint[] | { unread: string }>
}

export type RampWatch = {
    record(entry: JournalEntry): void
    gate: StepGate
    halt: AbortSignal
    stopped(): RampStop | undefined
    settled(): ReadonlyMap<number, readonly BarResult[]>
}

const REFUSED_AT_INTAKE = 'refused_at_intake'

const iso = (at: number): string => new Date(at).toISOString()

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

const harness = (step: DrivenStep, by: 'generator' | 'run_host'): Broke => ({
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
    const shortfall = shortfallOf(step, live.minOffered)
    if (shortfall) {
        return { stop: { end: 'harness_limit', reason: shortfall, broke: harness(step, 'generator') } }
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
                      })
                  ),
                  step
              )
            : undefined
    if (admitted) {
        return { stop: admitted }
    }
    const writerCpu = await live.writerCpu(span)
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
    const broke = results.find(({ breakingPoint }) => breakingPoint !== undefined)
    if (broke) {
        const { scale, at, part } = broke.breakingPoint!
        return {
            results,
            stop: {
                end: 'broke',
                reason: `${broke.name} broke at the ${scale}x step`,
                broke: { scale, offeredPerSecond: perSecond(offered, step), by: broke.name, kind: 'bar', at, part },
            },
        }
    }
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

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

export function watchRamp(live: LiveRamp, signal: AbortSignal): RampWatch {
    const halt = new AbortController()
    const refused: JournalEntry[] = []
    const settled = new Map<number, readonly BarResult[]>()
    const gate = live.gates[REFUSED_AT_INTAKE] ?? 0
    let stop: RampStop | undefined

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
        record: (entry) => {
            if (stop !== undefined || !live.judgesRefusals || refusalsOf([entry]).length === 0) {
                return
            }
            refused.push(entry)
            if (refused.length <= gate) {
                return
            }
            const crossedBy = crossedByOf(refused, refused, gate)
            const index = refused.find(({ unitId }) => unitId === crossedBy)?.step
            if (index !== undefined) {
                stopWith({
                    index,
                    end: 'broke',
                    reason: `${REFUSED_AT_INTAKE} went over its gate of ${gate} with ${refused.length} refused`,
                })
            }
        },
        gate: async (window, offered) => {
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
                stopWith({
                    index: window.index,
                    end: 'harness_limit',
                    reason: `the live judge failed at the ${window.scale}x step: ${messageOf(error)}`,
                    broke: harness({ ...window, offeredUnits: offered() }, 'run_host'),
                })
            }
        },
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
}

type Candidate = { index: number; rank: number; broke: Broke; reason: string }

const RANK = { generator: 0, bar: 1, gate: 2, invariant: 2, run_host: 3 } as const

const rankOf = (broke: Broke): number => (broke.kind === 'harness' ? RANK[broke.by] : RANK[broke.kind])

function candidatesOf({ planned, steps, minOffered, stop, bars, invariants, gates, journal }: RampEvidence): {
    placed: Candidate[]
    unplaced: Broke[]
} {
    const indexOfScale = (scale: number): number => steps.findIndex((step) => step.scale === scale)
    const placed: Candidate[] = []
    const add = (index: number, broke: Broke, reason: string): void => {
        if (index >= 0 && index < steps.length) {
            placed.push({ index, rank: rankOf(broke), broke, reason })
        }
    }
    const cutShort = (step: DrivenStep): boolean =>
        stop !== undefined &&
        step.index === steps.length - 1 &&
        step.endedAt - step.startedAt < planned[step.index].toMs - planned[step.index].fromMs
    for (const step of steps) {
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
    const stepOf = new Map(journal.map(({ unitId, step }) => [unitId, step]))
    const unplaced: Broke[] = []
    for (const { name, passed, crossedBy } of invariants) {
        if (passed) {
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
            `${name} broke at the ${step.scale}x step`
        )
    }
    return { placed, unplaced }
}

export function rampOf(evidence: RampEvidence): Ramp {
    const { planned, steps, admissions } = evidence
    const sustainedBefore = (index: number): number | null => (index > 0 ? steps[index - 1].scale : null)
    const admitted = steps[0] && admissionLimitOf(admissions, steps[0])
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
    const { placed, unplaced } = candidatesOf(evidence)
    const [first] = placed.sort((a, b) => a.index - b.index || a.rank - b.rank)
    if (interrupted && first?.index === last?.index && first.broke.kind === 'harness') {
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
    const ceiling = planned[planned.length - 1].scale
    return { end: 'ceiling', sustainedScale: ceiling, reason: `every step held up to the ${ceiling}x ceiling` }
}
