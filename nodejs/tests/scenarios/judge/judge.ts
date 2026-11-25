import { setTimeout as sleep } from 'timers/promises'

import type { ResidentBacklog } from '../backlog/backlog'
import type { Named } from '../cards'
import type { SeedState } from '../generator/generator'
import type { CyclotronProbe } from '../probe/cyclotron-probe'
import type { TruthRecord } from '../provider-edge'
import { TRUTH_PAGE_LIMIT } from '../provider-edge/truth'
import { INVARIANTS, deliveryKey, residentBacklogIntact } from './invariants'
import type { JudgeEvidence, RunBoundary } from './invariants'
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
const FINAL_PASSES = 3
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
    let truthFrom = 0
    let horizon: RunBoundary['horizon']
    let teams: number[] = []
    let unread: string | undefined
    let unsettled: string | undefined

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

    const pullToHead = async (
        signal?: AbortSignal
    ): Promise<{ runRecordsPastHead: boolean; fullPageAtHead: boolean }> => {
        let head: number | undefined
        let runRecordsPastHead = false
        let fullPageAtHead = false
        const isRunRecord = ofThisRun()
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
                runRecordsPastHead ||= page.records.some((record) => record.seq > head! && isRunRecord(record))
                fullPageAtHead = page.records.length >= TRUTH_PAGE_LIMIT && page.records.at(-1)!.seq === head
                if (records.length === 0) {
                    throw new Error(`the edge answered no records past ${cursor}`)
                }
                truth.push(...records)
                cursor = records.at(-1)!.seq
            }
            return { runRecordsPastHead, fullPageAtHead }
        } catch (error) {
            const at = head === undefined ? cursor : `${cursor} of ${head}`
            throw new Error(`the truth read hit a harness limit at record ${at}: ${messageOf(error)}`)
        }
    }

    const readToSettledHead = async (signal?: AbortSignal): Promise<void> => {
        await pullToHead(signal)
        for (let pass = 2; pass <= FINAL_PASSES; pass++) {
            const settled = runRecords()
            const { runRecordsPastHead, fullPageAtHead } = await pullToHead(signal)
            if (runRecords() === settled && !runRecordsPastHead && !fullPageAtHead) {
                return
            }
        }
        unsettled = `the edge kept accepting this run's sends through ${FINAL_PASSES} final reads of the truth`
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

    const ofThisRun = (): ((record: TruthRecord) => boolean) => {
        const units = new Set(journal.map(({ unitId }) => unitId))
        return ({ unitId }) => unitId !== undefined && units.has(unitId)
    }

    const runRecords = (): number => truth.filter(ofThisRun()).length

    return {
        async open(seed) {
            journal = []
            cursor = await source.head()
            truthFrom = cursor
            horizon = undefined
            truth = []
            unread = undefined
            unsettled = undefined
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
                    const settled = runRecords()
                    jobs = await probe.unfinishedJobs({ teams, queues: ['hogflow', 'email'] })
                    await pullTruth()
                    return runRecords() === settled
                })
                const unrecorded = unrecordedUnits()
                const tookMs = now() - startedAt
                const converged = jobs === 0 && quiet === true && unrecorded.length === 0 && tookMs <= withinMs
                if (converged || tookMs >= withinMs || signal.aborted) {
                    horizon = signal.aborted
                        ? undefined
                        : quiet === undefined && unread !== undefined
                          ? { unread }
                          : { seq: cursor, at: now() }
                    return {
                        converged,
                        unfinishedJobs: quiet === undefined && jobs === 0 ? null : (jobs ?? null),
                        unrecorded,
                        tookMs,
                        ...(unread !== undefined && { unread }),
                    }
                }
                await sleep(Math.min(pollMs, withinMs - tookMs), undefined, { signal }).catch(() => undefined)
            }
        },

        async check(invariants, gates, run, signal) {
            unsettled = undefined
            await read(() => readToSettledHead(signal))
            const resident = invariants.some(({ name }) => name === residentBacklogIntact.name)
                ? await residentBacklog?.()
                : undefined
            const boundary = {
                truthFrom,
                horizon,
                unobserved: run.unobserved,
                ...(unread !== undefined && { unread }),
                ...(unsettled !== undefined && { unsettled }),
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
