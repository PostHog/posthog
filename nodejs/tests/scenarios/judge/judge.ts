import { setTimeout as sleep } from 'timers/promises'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { Named } from '../cards'
import type { SeedState } from '../generator/generator'
import type { CyclotronProbe } from '../probe/cyclotron-probe'
import type { TruthHead, TruthPage, TruthRecord } from '../provider-edge'
import { INVARIANTS, deliveryKey } from './invariants'

export type JournalEntry = {
    unitId: string
    kind: 'event' | 'transactional'
    teamId: number
    offeredAt: number
    answer:
        | { accepted: true }
        | { accepted: false; transportError: string }
        | { accepted: false; status: number; outcome?: string }
    expect: { deliveries: string[] }
}

export type Convergence = { converged: boolean; unfinishedJobs: number; unrecorded: string[]; tookMs: number }

export type InvariantResult = {
    name: string
    passed: boolean
    observed: number
    gate?: number
    violation?: string
    unitIds: string[]
}

export interface Judge {
    open(seed: Pick<SeedState, 'teamIds'>): Promise<void>
    record(unit: JournalEntry): void
    converge(withinMs: number, signal: AbortSignal): Promise<Convergence>
    check(invariants: Named[], gates: Record<string, number>): Promise<InvariantResult[]>
    evidence(): { journal: JournalEntry[]; truth: TruthRecord[] }
}

export type JudgeOptions = {
    edgeUrl: string
    probe: Pick<CyclotronProbe, 'unfinishedJobs'>
    pollMs?: number
    now?: () => number
}

export function createJudge({ edgeUrl, probe, pollMs = 1000, now = Date.now }: JudgeOptions): Judge {
    let journal: JournalEntry[] = []
    let truth: TruthRecord[] = []
    let cursor = 0
    let teams: number[] = []

    const pullTruth = async (): Promise<void> => {
        for (;;) {
            const response = await internalFetch(`${edgeUrl}/_truth?after=${cursor}`)
            if (response.status !== 200) {
                throw new Error(`The edge answered /_truth with ${response.status}`)
            }
            const page = parseJSON(await response.text()) as TruthPage
            if (page.records.length === 0) {
                return
            }
            truth.push(...page.records)
            cursor = page.next
        }
    }

    const truthHead = async (): Promise<number> => {
        const response = await internalFetch(`${edgeUrl}/_truth/head`)
        if (response.status !== 200) {
            throw new Error(`The edge answered /_truth/head with ${response.status}`)
        }
        return (parseJSON(await response.text()) as TruthHead).head
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
            cursor = await truthHead()
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

        async check(invariants, gates) {
            await pullTruth()
            return invariants.map(({ name }) => {
                const definition = INVARIANTS.find((invariant) => invariant.name === name)
                if (!definition) {
                    throw new Error(`No invariant ${name}`)
                }
                return { name, gate: gates[name], ...definition.check({ journal, truth }, gates[name]) }
            })
        },

        evidence: () => ({ journal: [...journal], truth: [...truth] }),
    }
}
