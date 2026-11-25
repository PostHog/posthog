import { type LoadedCard, cardHashOf } from '../cards'
import type { DriveSummary } from '../generator/generator'
import { bouncedSuppressed, noLoss } from '../judge/invariants'
import type { DriveWindow, QueueSample } from '../judge/measurements'
import { pgFailover } from '../valves/valves'
import type { RunVerdict } from './runner'
import { type Admission, type Status, unobservedValvesOf, withEvidenceError } from './status'

export type PairRole = 'control' | 'faulted'

export type Attribution = 'fault' | 'open' | 'unjudged' | 'none'

export type Offered = Pick<DriveSummary, 'targetUnits' | 'offeredUnits'>

export type JudgedRun = {
    verdict: RunVerdict
    queue: readonly QueueSample[]
    drive?: DriveWindow
    units?: Offered
    evidenceError?: string
}

export type QueueCourse = { dueAtStart: number; peakDue: number; growth: number; peakOldestDueSeconds: number }

export type FaultDose = {
    valve: string
    target: string
    dose: Record<string, unknown>
    observedAt: string | null
    releasedAt: string | null
    error: string | null
}

export type NoLossResult = { passed: boolean; observed: number; violation: string | null; unjudged: string | null }

export type PairedRun = {
    role: PairRole
    runId: string
    status: Status
    statusReason: string
    admissions: Admission[]
    offered: Offered | null
    queue: QueueCourse | null
    drainSeconds: number | null
    faultDose: FaultDose[]
    noLoss: NoLossResult | null
}

export type Pair = {
    attribution: Attribution
    reason: string
    controlRunId: string
    faultedRunId: string | null
    runs: PairedRun[]
}

export type FaultedRun = JudgedRun | { missing: string }

export type ScorecardPair = Pair & { role: PairRole }

const CHECKS_OF_A_FAULT = new Set([bouncedSuppressed.name])

export function controlOf(loaded: LoadedCard): LoadedCard {
    const { card, profileHash } = loaded
    const control = {
        ...card,
        valves: [],
        invariants: card.invariants.filter(({ name }) => !CHECKS_OF_A_FAULT.has(name)),
        gates: Object.fromEntries(Object.entries(card.gates).filter(([name]) => !CHECKS_OF_A_FAULT.has(name))),
    }
    return { ...loaded, card: control, cardHash: cardHashOf(control, profileHash) }
}

export function pairProblemsOf({ card }: LoadedCard): string[] {
    if (card.valves.length === 0 || !card.invariants.some(({ name }) => name === noLoss.name)) {
        return [`${card.id}: --pair needs a card that applies valves and judges no_loss, or both runs end unjudged.`]
    }
    return card.valves.some(({ valve }) => valve === pgFailover.name)
        ? [`${card.id}: ${pgFailover.name} runs only on a run host, and --pair runs only locally.`]
        : []
}

function queueCourseOf({ queue, drive }: JudgedRun): QueueCourse | null {
    const counted = queue
        .filter(
            (sample) =>
                !('error' in sample) &&
                (drive === undefined || (sample.at >= drive.startedAt && sample.at <= drive.endedAt))
        )
        .sort((a, b) => a.at - b.at) as Exclude<QueueSample, { error: string }>[]
    if (counted.length === 0) {
        return null
    }
    const dueAtStart = counted[0].due
    const peakDue = Math.max(...counted.map(({ due }) => due))
    return {
        dueAtStart,
        peakDue,
        growth: peakDue - dueAtStart,
        peakOldestDueSeconds: Math.max(...counted.map(({ oldestDueSeconds }) => oldestDueSeconds)),
    }
}

function noLossOf({ invariants }: RunVerdict): NoLossResult | null {
    const result = invariants.find(({ name }) => name === noLoss.name)
    return result === undefined
        ? null
        : {
              passed: result.passed,
              observed: result.observed,
              violation: result.violation ?? null,
              unjudged: result.unjudged ?? null,
          }
}

function pairedRunOf(role: PairRole, run: JudgedRun, card: LoadedCard['card']): PairedRun {
    const { verdict } = run
    const { convergence } = verdict
    return {
        role,
        runId: verdict.runId,
        status: verdict.status,
        statusReason: verdict.statusReason,
        admissions: verdict.admissions,
        offered: run.units ?? null,
        queue: queueCourseOf(run),
        drainSeconds: convergence?.converged ? convergence.tookMs / 1000 : null,
        faultDose: verdict.timeline.map(({ valve, target, observedAt, releasedAt, error }, i) => ({
            valve,
            target,
            dose: card.valves[i]?.dose ?? {},
            observedAt: observedAt ?? null,
            releasedAt: releasedAt ?? null,
            error: error ?? null,
        })),
        noLoss: noLossOf(verdict),
    }
}

function unjudgedRunOf(name: string, { verdict }: JudgedRun): string | undefined {
    const result = noLossOf(verdict)
    if (result?.unjudged) {
        return `the ${name} run's no_loss was not judged: ${result.unjudged}`
    }
    if (verdict.status === 'invalid') {
        return `the ${name} run is invalid: ${verdict.statusReason}`
    }
    return result === null ? `the ${name} run judged no no_loss` : undefined
}

function uncarriedLoadOf(control: JudgedRun, faulted: JudgedRun): string | undefined {
    if (control.units === undefined || faulted.units === undefined) {
        return 'the offered load of a run was not recorded'
    }
    const { offeredUnits, targetUnits } = control.units
    return offeredUnits < targetUnits
        ? `the control offered ${offeredUnits} of its ${targetUnits} units, so it may not have carried the faulted run's load`
        : undefined
}

function unobservedFaultOf({ verdict, drive }: JudgedRun): string | undefined {
    if (verdict.timeline.length === 0) {
        return 'the faulted run applied no fault'
    }
    const unobserved = unobservedValvesOf(verdict.timeline, drive ?? { startedAt: 0, endedAt: Infinity })
    return unobserved.length === 0 ? undefined : `the fault evidence is missing: ${unobserved.join('; ')}`
}

function attributionOf(control: JudgedRun, faulted: FaultedRun): Pick<Pair, 'attribution' | 'reason'> {
    const unjudgedControl = unjudgedRunOf('control', control)
    if (unjudgedControl !== undefined) {
        return { attribution: 'unjudged', reason: unjudgedControl }
    }
    if (control.verdict.status === 'failed') {
        return {
            attribution: 'open',
            reason: `the control failed at the same seed and offered load, so the faulted run's result is not attributed to the fault: ${control.verdict.statusReason}`,
        }
    }
    if ('missing' in faulted) {
        return { attribution: 'unjudged', reason: `the faulted run did not run: ${faulted.missing}` }
    }
    const unjudgedFaulted =
        unobservedFaultOf(faulted) ?? unjudgedRunOf('faulted', faulted) ?? uncarriedLoadOf(control, faulted)
    if (unjudgedFaulted !== undefined) {
        return { attribution: 'unjudged', reason: unjudgedFaulted }
    }
    const faultedNoLoss = noLossOf(faulted.verdict)!
    return faultedNoLoss.passed
        ? { attribution: 'none', reason: 'the control and the faulted run both held no_loss' }
        : {
              attribution: 'fault',
              reason: `the control held no_loss at the same seed and offered load, and the faulted run did not: ${faultedNoLoss.violation ?? 'no violation named'}`,
          }
}

const withEvidenceOf = (run: JudgedRun): JudgedRun => ({
    ...run,
    verdict: withEvidenceError(run.verdict, run.evidenceError),
})

export function pairOf(loaded: LoadedCard, judgedControl: JudgedRun, judgedFaulted: FaultedRun): Pair {
    const control = withEvidenceOf(judgedControl)
    const faulted = 'missing' in judgedFaulted ? judgedFaulted : withEvidenceOf(judgedFaulted)
    return {
        ...attributionOf(control, faulted),
        controlRunId: control.verdict.runId,
        faultedRunId: 'missing' in faulted ? null : faulted.verdict.runId,
        runs: [
            pairedRunOf('control', control, controlOf(loaded).card),
            ...('missing' in faulted ? [] : [pairedRunOf('faulted', faulted, loaded.card)]),
        ],
    }
}
