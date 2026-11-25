import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { EMAIL_ACTION } from '../generator/traffic'
import { COUNTERS, Counted, CounterProbe, CounterQuery } from '../probe/counter-probe'
import type { TruthRecord } from '../provider-edge'
import { deliveryKey } from './invariants'
import type { JournalEntry } from './judge'
import type { MeasurementDefinition } from './measurements'

export type CounterReading = { counted: Counted; incomplete?: true } | { unread: string }

export type CounterRead = { withinMs: number; quietMs: number; pollMs: number }

export const COUNTER_READ: CounterRead = { withinMs: 60_000, quietMs: 15_000, pollMs: 1000 }

type Evidence = { journal: readonly JournalEntry[]; truth: readonly TruthRecord[] }

const isAccepted = (status: number): boolean => status >= 200 && status < 300

// The email worker reschedules a throttled send and counts no failure for it.
const THROTTLED = 429

const ofThisRun = ({ journal, truth }: Evidence): TruthRecord[] => {
    const units = new Set(journal.map(({ unitId }) => unitId))
    return truth.filter(({ unitId }) => unitId !== undefined && units.has(unitId))
}

export function sinkCountsOf(evidence: Evidence): Counted {
    const ours = ofThisRun(evidence)
    const sends = ours.filter(({ kind }) => kind === 'ses.send')
    const keyOf = ({ unitId, actionId, flowId }: TruthRecord): string =>
        `${deliveryKey(unitId!, actionId ?? '')} ${flowId ?? ''}`
    const accepted = new Set(sends.filter(({ status }) => isAccepted(status)).map(keyOf))
    const refused = new Set(sends.filter(({ status }) => !isAccepted(status) && status !== THROTTLED).map(keyOf))
    return {
        email_sent: sends.filter(({ status }) => isAccepted(status)).length,
        // The edge publishes a notification only for a bounce, never for a delivery.
        email_delivered: 0,
        email_bounced: ours.filter(
            ({ kind, status, detail }) => kind === 'ses.feedback' && detail.feedback && isAccepted(status)
        ).length,
        email_failed: [...refused].filter((key) => !accepted.has(key)).length,
    }
}

export const owedOf = (journal: readonly JournalEntry[]): number =>
    journal
        .filter(({ answer, expect }) => answer.accepted && expect.deliveries.includes(EMAIL_ACTION))
        .reduce((sum, { followUp }) => sum + (followUp && 'accepted' in followUp && followUp.accepted ? 2 : 1), 0)

const same = (a: Counted, b: Counted): boolean => COUNTERS.every((counter) => a[counter] === b[counter])

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

export type ReadClock = { now?: () => number; pause?: (ms: number, signal?: AbortSignal) => Promise<unknown> }

export async function readCounters(
    probe: CounterProbe,
    query: CounterQuery,
    expected: Counted,
    { withinMs, quietMs, pollMs }: CounterRead,
    signal?: AbortSignal,
    { now = Date.now, pause = (ms, abort) => sleep(ms, undefined, { signal: abort }) }: ReadClock = {}
): Promise<CounterReading> {
    const startedAt = now()
    let last: Counted | undefined
    let changedAt = startedAt
    let failure: string | undefined
    for (;;) {
        try {
            const counted = await probe.counted(query)
            failure = undefined
            if (same(counted, expected)) {
                return { counted }
            }
            if (last === undefined || !same(counted, last)) {
                last = counted
                changedAt = now()
            } else if (now() - changedAt >= quietMs) {
                return { counted }
            }
        } catch (error) {
            failure = messageOf(error)
        }
        if (now() - startedAt >= withinMs || signal?.aborted) {
            if (last === undefined) {
                return { unread: failure ?? 'the run stopped before the counters were read' }
            }
            return { counted: last, incomplete: true }
        }
        await pause(pollMs, signal).catch(() => undefined)
    }
}

const unknown = (reason: string): { value: null; censored: true; unmeasured: string } => ({
    value: null,
    censored: true,
    unmeasured: reason,
})

const EVENTS_UNMEASURED = {
    key: 'email_sent_events',
    ...unknown('the scenario stack runs no ingestion, so no $workflows_email_sent event can be counted'),
}

export const counterDrift: MeasurementDefinition = {
    name: 'counter_drift',
    params: z.object({}).strict(),
    unit: 'messages',
    measure: ({ journal, truth, counters, unread }) => {
        if (counters === undefined) {
            return []
        }
        if ('unread' in counters) {
            return [...COUNTERS.map((counter) => ({ key: counter, ...unknown(counters.unread) })), EVENTS_UNMEASURED]
        }
        const sink = unread === undefined ? sinkCountsOf({ journal, truth }) : undefined
        const truthUnread = unknown(`the truth could not be read: ${unread}`)
        const incomplete = counters.incomplete ? { incomplete: true as const } : {}
        return [
            { key: 'owed', value: owedOf(journal) },
            ...COUNTERS.flatMap((counter) => [
                {
                    key: counter,
                    ...(sink ? { value: counters.counted[counter] - sink[counter], ...incomplete } : truthUnread),
                },
                { key: `${counter}_counted`, value: counters.counted[counter], ...incomplete },
                { key: `${counter}_sink`, ...(sink ? { value: sink[counter] } : truthUnread) },
            ]),
            EVENTS_UNMEASURED,
        ]
    },
}
