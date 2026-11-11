import { setTimeout as sleep } from 'timers/promises'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { Named } from '../cards'
import type { SeedState } from '../generator/generator'
import type { CyclotronProbe } from '../probe/cyclotron-probe'
import type { TruthPage, TruthRecord } from '../provider-edge'
import { INVARIANTS, deliveryKey } from './invariants'

export type JournalEntry = {
    unitId: string
    kind: 'event' | 'transactional'
    teamId: number
    offeredAt: number
    answer:
        | { accepted: true }
        | { accepted: false; status: number; outcome?: string }
        | { accepted: false; transportError: string }
    expect: { deliveries: string[]; refusal?: string }
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

export type Measurement = { name: string; of?: string; value: number; unit: string }

export interface Judge {
    open(seed: SeedState): Promise<void>
    record(unit: JournalEntry): void
    converge(withinMs: number, signal: AbortSignal): Promise<Convergence>
    check(invariants: Named[], gates: Record<string, number>): Promise<InvariantResult[]>
    measure(measurements: Named[]): Promise<Measurement[]>
    evidence(): { journal: JournalEntry[]; truth: TruthRecord[] }
}

export type JudgeOptions = { edgeUrl: string; probe: CyclotronProbe; pollMs?: number }

export function createJudge({ edgeUrl, probe, pollMs = 1000 }: JudgeOptions): Judge {
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
            await pullTruth()
            truth = []
            teams = seed.teams.map(({ teamId }) => teamId)
        },

        record(unit) {
            journal.push(unit)
        },

        async converge(withinMs, signal) {
            const startedAt = Date.now()
            for (;;) {
                await pullTruth()
                const { running, available, scheduledLater } = await probe.counts({
                    teams,
                    queues: ['hogflow', 'email'],
                })
                const unfinishedJobs = running + available + scheduledLater
                const unrecorded = unrecordedUnits()
                const tookMs = Date.now() - startedAt
                const converged = unfinishedJobs === 0 && unrecorded.length === 0
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

        measure: () => Promise.resolve([]),

        evidence: () => ({ journal: [...journal], truth: [...truth] }),
    }
}
