import { setTimeout as sleep } from 'timers/promises'

import type { ResidentBacklog } from '../backlog/backlog'
import type { Named } from '../cards'
import type { SeedState } from '../generator/generator'
import type { CyclotronProbe } from '../probe/cyclotron-probe'
import type { TruthRecord } from '../provider-edge'
import { INVARIANTS, deliveryKey, residentBacklogIntact } from './invariants'
import type { JudgeEvidence, RunBoundary } from './invariants'
import type { TruthSource } from './truth'

export type IntakeAnswer = (
    | { accepted: true }
    | { accepted: false; transportError: string }
    | { accepted: false; status: number; outcome?: string }
) & { retries?: number }

export type FollowUpAnswer = IntakeAnswer | { notSent: string }

export type JournalEntry = {
    unitId: string
    kind: 'event' | 'capture' | 'transactional'
    teamId: number
    offeredAt: number
    step?: number
    answer: IntakeAnswer
    expect: { deliveries: string[]; dueAt?: number }
    followUp?: FollowUpAnswer
}

export type Convergence = {
    converged: boolean
    unfinishedJobs: number | null
    unrecorded: string[]
    tookMs: number
    unread?: string
}

export type InvariantResult = {
    name: string
    passed: boolean
    observed: number
    gate?: number
    violation?: string
    unitIds: string[]
    crossedBy?: string
    unjudged?: string
    missing?: string[]
    extra?: string[]
}

export type RunEvidence = Pick<JudgeEvidence, 'janitorResets'> & Pick<RunBoundary, 'unobserved'>

export interface Judge {
    open(seed: Pick<SeedState, 'teamIds'>): Promise<void>
    record(unit: JournalEntry): void
    converge(withinMs: number, signal: AbortSignal): Promise<Convergence>
    check(invariants: Named[], gates: Record<string, number>, run: RunEvidence): Promise<InvariantResult[]>
    evidence(): { journal: JournalEntry[]; truth: TruthRecord[]; fetchRetries: number; unread?: string }
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
    let truthFrom = 0
    let horizon: RunBoundary['horizon']
    let teams: number[] = []
    let unread: string | undefined

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

    const read = async <T>(what: () => Promise<T>): Promise<T | undefined> => {
        try {
            const value = await what()
            unread = undefined
            return value
        } catch (error) {
            unread = error instanceof Error ? error.message : String(error)
            return undefined
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
            truthFrom = cursor
            horizon = undefined
            truth = []
            unread = undefined
            teams = [...seed.teamIds]
        },

        record(unit) {
            journal.push(unit)
        },

        async converge(withinMs, signal) {
            const startedAt = now()
            for (;;) {
                let jobs: number | undefined
                const quiet = await read(async () => {
                    await pullTruth()
                    const settled = cursor
                    jobs = await probe.unfinishedJobs({ teams, queues: ['hogflow', 'email'] })
                    await pullTruth()
                    return cursor === settled
                })
                const unrecorded = unrecordedUnits()
                const tookMs = now() - startedAt
                const converged = jobs === 0 && quiet === true && unrecorded.length === 0 && tookMs <= withinMs
                if (converged || tookMs >= withinMs || signal.aborted) {
                    horizon = signal.aborted ? undefined : { seq: cursor, at: now() }
                    return {
                        converged,
                        unfinishedJobs: jobs ?? null,
                        unrecorded,
                        tookMs,
                        ...(unread !== undefined && { unread }),
                    }
                }
                await sleep(Math.min(pollMs, withinMs - tookMs), undefined, { signal }).catch(() => undefined)
            }
        },

        async check(invariants, gates, run) {
            await read(pullTruth)
            const resident = invariants.some(({ name }) => name === residentBacklogIntact.name)
                ? await residentBacklog?.()
                : undefined
            const boundary = {
                truthFrom,
                horizon,
                unobserved: run.unobserved,
                ...(unread !== undefined && { unread }),
            }
            const evidence = { journal, truth, fetchRetries, resident, janitorResets: run.janitorResets, boundary }
            return invariants.map(({ name, params }) => {
                const definition = INVARIANTS.find((invariant) => invariant.name === name)
                if (!definition) {
                    throw new Error(`No invariant ${name}`)
                }
                return { name, gate: gates[name], ...definition.check(evidence, gates[name], params) }
            })
        },

        evidence: () => ({
            journal: [...journal],
            truth: [...truth],
            fetchRetries,
            ...(unread !== undefined && { unread }),
        }),
    }
}
