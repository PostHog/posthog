import { setTimeout as sleep } from 'timers/promises'

import type { ResidentBacklog } from '../backlog/backlog'
import type { Named } from '../cards'
import type { SeedState } from '../generator/generator'
import type { CyclotronProbe } from '../probe/cyclotron-probe'
import type { TruthRecord } from '../provider-edge'
import { INVARIANTS, deliveryKey, residentBacklogIntact } from './invariants'
import type { JudgeEvidence } from './invariants'
import type { TruthRead, TruthSource } from './truth'

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
    expect: { deliveries: string[] }
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
}

export type RunEvidence = Pick<JudgeEvidence, 'janitorResets'>

export interface Judge {
    open(seed: Pick<SeedState, 'teamIds'>): Promise<void>
    record(unit: JournalEntry): void
    converge(withinMs: number, signal: AbortSignal): Promise<Convergence>
    check(
        invariants: Named[],
        gates: Record<string, number>,
        run: RunEvidence,
        signal?: AbortSignal
    ): Promise<InvariantResult[]>
    evidence(): { journal: JournalEntry[]; truth: TruthRecord[]; fetchRetries: number; unread?: string }
}

export type JudgeOptions = {
    truth: TruthSource
    probe: Pick<CyclotronProbe, 'unfinishedJobs'>
    fetchRetries: number
    residentBacklog?: () => Promise<ResidentBacklog>
    finalRead?: FinalRead
    pollMs?: number
    now?: () => number
}

export type FinalRead = { attempts: number; backoffMs: number }

const FINAL_READ: FinalRead = { attempts: 3, backoffMs: 1000 }
const FINAL: TruthRead = { final: true }

const messageOf = (error: unknown): string =>
    typeof error === 'object' && error !== null && 'message' in error ? String(error.message) : String(error)

async function retried<T>(
    read: () => Promise<T>,
    { attempts, backoffMs }: FinalRead,
    signal?: AbortSignal
): Promise<T> {
    for (let attempt = 1; ; attempt++) {
        try {
            return await read()
        } catch (error) {
            if (attempt < attempts) {
                await sleep(backoffMs * attempt, undefined, { signal }).catch(() => undefined)
            }
            if (attempt >= attempts || signal?.aborted) {
                throw new Error(`${attempt} of ${attempts} attempts failed, the last with ${messageOf(error)}`)
            }
        }
    }
}

export function createJudge({
    truth: source,
    probe,
    fetchRetries,
    residentBacklog,
    finalRead = FINAL_READ,
    pollMs = 1000,
    now = Date.now,
}: JudgeOptions): Judge {
    let journal: JournalEntry[] = []
    let truth: TruthRecord[] = []
    let cursor = 0
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

    const pullToHead = async (signal?: AbortSignal): Promise<void> => {
        let head: number | undefined
        try {
            if (signal?.aborted) {
                throw new Error('the run was stopped')
            }
            const sampled = await retried(() => source.head(FINAL), finalRead, signal)
            if (!Number.isInteger(sampled)) {
                throw new Error('the edge answered no head')
            }
            head = sampled
            while (cursor < head) {
                if (signal?.aborted) {
                    throw new Error('the run was stopped')
                }
                const page = await retried(() => source.after(cursor, FINAL), finalRead, signal)
                const records = page.records.filter(({ seq }) => seq > cursor && seq <= head!)
                if (records.length === 0) {
                    throw new Error(`the edge answered no records past ${cursor}`)
                }
                truth.push(...records)
                cursor = records.at(-1)!.seq
            }
        } catch (error) {
            const at = head === undefined ? cursor : `${cursor} of ${head}`
            throw new Error(`the truth read hit a harness limit at record ${at}: ${messageOf(error)}`)
        }
    }

    const read = async <T>(what: () => Promise<T>): Promise<T | undefined> => {
        try {
            const value = await what()
            unread = undefined
            return value
        } catch (error) {
            unread = messageOf(error)
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
                const polled = await read(async () => {
                    await pullTruth()
                    return probe.unfinishedJobs({ teams, queues: ['hogflow', 'email'] })
                })
                const unrecorded = unrecordedUnits()
                const tookMs = now() - startedAt
                const converged = polled === 0 && unrecorded.length === 0 && tookMs <= withinMs
                if (converged || tookMs >= withinMs || signal.aborted) {
                    return {
                        converged,
                        unfinishedJobs: polled ?? null,
                        unrecorded,
                        tookMs,
                        ...(unread !== undefined && { unread }),
                    }
                }
                await sleep(Math.min(pollMs, withinMs - tookMs), undefined, { signal }).catch(() => undefined)
            }
        },

        async check(invariants, gates, run, signal) {
            await read(() => pullToHead(signal))
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

        evidence: () => ({
            journal: [...journal],
            truth: [...truth],
            fetchRetries,
            ...(unread !== undefined && { unread }),
        }),
    }
}
