import { setTimeout as sleep } from 'timers/promises'

import type { ResidentBacklog } from '../backlog/backlog'
import type { Named } from '../cards'
import type { SeedState } from '../generator/generator'
import type { CyclotronProbe } from '../probe/cyclotron-probe'
import type { TruthRecord } from '../provider-edge'
import { INVARIANTS, deliveryKey, residentBacklogIntact } from './invariants'
import type { JudgeEvidence } from './invariants'
import type { TruthSource } from './truth'

export type IntakeAnswer =
    | { accepted: true }
    | { accepted: false; transportError: string }
    | { accepted: false; status: number; outcome?: string }

export type FollowUpAnswer = IntakeAnswer | { notSent: string }

export type JournalEntry = {
    unitId: string
    kind: 'event' | 'capture' | 'transactional'
    teamId: number
    offeredAt: number
    step?: number
    answer: IntakeAnswer
    expect: { deliveries: string[] }
    followUp?: FollowUpAnswer
}

export type Convergence = { converged: boolean; unfinishedJobs: number; unrecorded: string[]; tookMs: number }

export type InvariantResult = {
    name: string
    passed: boolean
    observed: number
    gate?: number
    violation?: string
    unitIds: string[]
    crossedBy?: string
}

export type RunEvidence = Pick<JudgeEvidence, 'janitorResets'>

export interface Judge {
    open(seed: Pick<SeedState, 'teamIds'>): Promise<void>
    record(unit: JournalEntry): void
    converge(withinMs: number, signal: AbortSignal): Promise<Convergence>
    check(invariants: Named[], gates: Record<string, number>, run: RunEvidence): Promise<InvariantResult[]>
    evidence(): { journal: JournalEntry[]; truth: TruthRecord[]; fetchRetries: number }
}

export type JudgeOptions = {
    truth: TruthSource
    probe: Pick<CyclotronProbe, 'unfinishedJobs'>
    fetchRetries: number
    residentBacklog?: () => Promise<ResidentBacklog>
    pollMs?: number
    now?: () => number
}

export function createJudge({
    truth: source,
    probe,
    fetchRetries,
    residentBacklog,
    pollMs = 1000,
    now = Date.now,
}: JudgeOptions): Judge {
    let journal: JournalEntry[] = []
    let truth: TruthRecord[] = []
    let cursor = 0
    let teams: number[] = []

    const pullTruth = async (): Promise<void> => {
        for (;;) {
            const page = await source.after(cursor)
            if (page.records.length === 0) {
                return
            }
            truth.push(...page.records)
            cursor = page.next
        }
    }

    const unrecordedUnits = (): string[] => {
        const recorded = new Set(
            truth.flatMap(({ unitId, actionId }) =>
                unitId !== undefined && actionId !== undefined ? [deliveryKey(unitId, actionId)] : []
            )
        )
        return journal
            .filter(
                ({ answer, unitId, expect }) =>
                    answer.accepted &&
                    expect.deliveries.some((actionId) => !recorded.has(deliveryKey(unitId, actionId)))
            )
            .map(({ unitId }) => unitId)
    }

    return {
        async open(seed) {
            journal = []
            cursor = await source.head()
            truth = []
            teams = [...seed.teamIds]
        },

        record(unit) {
            journal.push(unit)
        },

        async converge(withinMs, signal) {
            const startedAt = now()
            for (;;) {
                await pullTruth()
                const unfinishedJobs = await probe.unfinishedJobs({ teams, queues: ['hogflow', 'email'] })
                const unrecorded = unrecordedUnits()
                const tookMs = now() - startedAt
                const converged = unfinishedJobs === 0 && unrecorded.length === 0 && tookMs <= withinMs
                if (converged || tookMs >= withinMs || signal.aborted) {
                    return { converged, unfinishedJobs, unrecorded, tookMs }
                }
                await sleep(Math.min(pollMs, withinMs - tookMs), undefined, { signal }).catch(() => undefined)
            }
        },

        async check(invariants, gates, run) {
            await pullTruth()
            const resident = invariants.some(({ name }) => name === residentBacklogIntact.name)
                ? await residentBacklog?.()
                : undefined
            return invariants.map(({ name }) => {
                const definition = INVARIANTS.find((invariant) => invariant.name === name)
                if (!definition) {
                    throw new Error(`No invariant ${name}`)
                }
                const evidence = { journal, truth, fetchRetries, resident, ...run }
                return { name, gate: gates[name], ...definition.check(evidence, gates[name]) }
            })
        },

        evidence: () => ({ journal: [...journal], truth: [...truth], fetchRetries }),
    }
}
