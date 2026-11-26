import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { EMAIL_ACTION } from '../generator/traffic'
import { COUNTERS, Counted, CounterProbe, CounterQuery } from '../probe/counter-probe'
import type { TruthRecord } from '../provider-edge'
import { isAccepted, owedOf } from './invariants'
import type { JournalEntry } from './judge'
import type { MeasurementDefinition } from './measurements'

export type CounterReading =
    | { counted: Counted; consumers?: number; consumersUnread?: string; incomplete?: true }
    | { unread: string }

export type CounterRead = { withinMs: number; quietMs: number; pollMs: number }

export const COUNTER_READ: CounterRead = { withinMs: 60_000, quietMs: 15_000, pollMs: 1000 }

type Evidence = { journal: readonly JournalEntry[]; truth: readonly TruthRecord[] }

const ofThisRun = ({ journal, truth }: Evidence): TruthRecord[] => {
    const units = new Set(journal.map(({ unitId }) => unitId))
    return truth.filter(({ unitId }) => unitId !== undefined && units.has(unitId))
}

type SinkCounts = Pick<Counted, 'email_sent' | 'email_delivered'>

function sinkCountsOf(evidence: Evidence): SinkCounts {
    return {
        email_sent: ofThisRun(evidence).filter(({ kind, status }) => kind === 'ses.send' && isAccepted(status)).length,
        email_delivered: 0,
    }
}

const FAILURES_LEFT_OUT =
    'the sink cannot tell a refused send the worker retried and sent from a refused send that another invocation of the unit sent, so it can miss a failure the counter holds'

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
            const recovered = failure !== undefined
            failure = undefined
            if (recovered || last === undefined || !same(counted, last)) {
                last = counted
                changedAt = now()
            } else if (now() - changedAt >= quietMs) {
                return fedBy(probe, counted)
            }
        } catch (error) {
            failure = messageOf(error)
        }
        if (now() - startedAt >= withinMs) {
            break
        }
        await pause(pollMs, signal).catch(() => undefined)
    }
    if (last === undefined) {
        return { unread: failure ?? 'the run stopped before the counters were read' }
    }
    return { ...(await fedBy(probe, last)), incomplete: true }
}

const fedBy = async (
    probe: CounterProbe,
    counted: Counted
): Promise<{ counted: Counted; consumers?: number; consumersUnread?: string }> => {
    try {
        return { counted, consumers: await probe.consumers() }
    } catch (error) {
        return { counted, consumersUnread: messageOf(error) }
    }
}

const unknown = (reason: string): { value: null; censored: true; unmeasured: string } => ({
    value: null,
    censored: true,
    unmeasured: reason,
})

const UNMEASURED = [
    {
        key: 'email_sent_events',
        ...unknown('the scenario stack runs no ingestion, so no $workflows_email_sent event can be counted'),
    },
    {
        key: 'email_bounced',
        ...unknown('the edge records a bounce only after the SES webhook answers, so the sink can trail the counter'),
    },
]

export const counterDrift: MeasurementDefinition = {
    name: 'counter_drift',
    params: z.object({}).strict(),
    unit: 'messages',
    measure: ({ journal, truth, counters, unread, horizonAt, converged, unsettled: stillSending }) => {
        if (counters === undefined) {
            return []
        }
        const read = 'unread' in counters ? undefined : counters
        const sink = unread === undefined ? sinkCountsOf({ journal, truth }) : undefined
        const noCount = unknown('unread' in counters ? counters.unread : '')
        const noSink = unknown(`the truth could not be read: ${unread}`)
        const unsettled = unknown(
            stillSending ?? 'the run did not converge, so sends could still land while the counters were read'
        )
        const fedTwice = unknown(
            read?.consumers === undefined
                ? `ClickHouse could not say how many Kafka tables feed app_metrics2${read?.consumersUnread ? ` (${read.consumersUnread})` : ''}, so a count could land more than once`
                : `ClickHouse feeds app_metrics2 from ${read.consumers} Kafka tables, not one, so the counts do not match the sends one to one`
        )
        const incomplete = read?.incomplete ? { incomplete: true as const } : {}
        return [
            {
                key: 'owed',
                ...(horizonAt === undefined
                    ? unknown('the run reached no recovery horizon')
                    : { value: owedOf(journal, EMAIL_ACTION, horizonAt) }),
            },
            ...COUNTERS.flatMap((counter) => {
                const countedSide = {
                    key: `${counter}_counted`,
                    ...(read ? { value: read.counted[counter], ...incomplete } : noCount),
                }
                if (counter === 'email_failed') {
                    const leftOut = unknown(FAILURES_LEFT_OUT)
                    return [{ key: counter, ...leftOut }, countedSide, { key: `${counter}_sink`, ...leftOut }]
                }
                return [
                    {
                        key: counter,
                        ...(read === undefined
                            ? noCount
                            : sink === undefined
                              ? noSink
                              : converged === false || stillSending !== undefined
                                ? unsettled
                                : read.consumers !== 1
                                  ? fedTwice
                                  : { value: read.counted[counter] - sink[counter], ...incomplete }),
                    },
                    countedSide,
                    { key: `${counter}_sink`, ...(sink ? { value: sink[counter] } : noSink) },
                ]
            }),
            ...UNMEASURED,
        ]
    },
}
