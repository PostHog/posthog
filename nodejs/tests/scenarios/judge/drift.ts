import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { EMAIL_ACTION } from '../generator/traffic'
import { COUNTERS, Counted, CounterProbe, CounterQuery } from '../probe/counter-probe'
import type { TruthRecord } from '../provider-edge'
import { deliveryKey, isAccepted, isThrottled, owedOf } from './invariants'
import type { JournalEntry } from './judge'
import type { MeasurementDefinition } from './measurements'

export type CounterReading = { counted: Counted; incomplete?: true } | { unread: string }

export type CounterRead = { withinMs: number; quietMs: number; pollMs: number }

export const COUNTER_READ: CounterRead = { withinMs: 60_000, quietMs: 15_000, pollMs: 1000 }

type Evidence = { journal: readonly JournalEntry[]; truth: readonly TruthRecord[] }

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
    const refused = new Set(sends.filter((send) => !isAccepted(send.status) && !isThrottled(send)).map(keyOf))
    return {
        email_sent: sends.filter(({ status }) => isAccepted(status)).length,
        email_delivered: 0,
        email_bounced: ours.filter(
            ({ kind, status, detail }) => kind === 'ses.feedback' && detail.feedback && isAccepted(status)
        ).length,
        email_failed: [...refused].filter((key) => !accepted.has(key)).length,
    }
}

const same = (a: Counted, b: Counted): boolean => COUNTERS.every((counter) => a[counter] === b[counter])

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

export type ReadClock = { now?: () => number; pause?: (ms: number, signal?: AbortSignal) => Promise<unknown> }

export async function readCounters(
    probe: CounterProbe,
    query: CounterQuery,
    { withinMs, quietMs, pollMs }: CounterRead,
    signal?: AbortSignal,
    { now = Date.now, pause = (ms, abort) => sleep(ms, undefined, { signal: abort }) }: ReadClock = {}
): Promise<CounterReading> {
    const startedAt = now()
    let last: Counted | undefined
    let changedAt = startedAt
    let failure: string | undefined
    while (!signal?.aborted) {
        try {
            const counted = await probe.counted(query)
            failure = undefined
            if (last === undefined || !same(counted, last)) {
                last = counted
                changedAt = now()
            } else if (now() - changedAt >= quietMs) {
                return { counted }
            }
        } catch (error) {
            failure = messageOf(error)
            changedAt = now()
        }
        if (now() - startedAt >= withinMs) {
            break
        }
        await pause(pollMs, signal).catch(() => undefined)
    }
    if (last === undefined) {
        return { unread: failure ?? 'the run stopped before the counters were read' }
    }
    return { counted: last, incomplete: true }
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
    measure: ({ journal, truth, counters, unread, horizonAt }) => {
        if (counters === undefined) {
            return []
        }
        const read = 'unread' in counters ? undefined : counters
        const sink = unread === undefined ? sinkCountsOf({ journal, truth }) : undefined
        const noCount = unknown('unread' in counters ? counters.unread : '')
        const noSink = unknown(`the truth could not be read: ${unread}`)
        const incomplete = read?.incomplete ? { incomplete: true as const } : {}
        return [
            {
                key: 'owed',
                ...(horizonAt === undefined
                    ? unknown('the run reached no recovery horizon')
                    : { value: owedOf(journal, EMAIL_ACTION, horizonAt) }),
            },
            ...COUNTERS.flatMap((counter) => [
                {
                    key: counter,
                    ...(read === undefined
                        ? noCount
                        : sink === undefined
                          ? noSink
                          : { value: read.counted[counter] - sink[counter], ...incomplete }),
                },
                { key: `${counter}_counted`, ...(read ? { value: read.counted[counter], ...incomplete } : noCount) },
                { key: `${counter}_sink`, ...(sink ? { value: sink[counter] } : noSink) },
            ]),
            EVENTS_UNMEASURED,
        ]
    },
}
