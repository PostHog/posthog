import type { Counted, CounterProbe } from '../probe/counter-probe'
import type { TruthRecord } from '../provider-edge'
import { CounterReading, readCounters } from './drift'
import type { JournalEntry } from './judge'
import { MeasureEvidence, measure } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')

const offered = (unitId: string, deliveries = ['email'], extra: Partial<JournalEntry> = {}): JournalEntry => ({
    unitId,
    kind: 'event',
    teamId: 7,
    offeredAt: FROM,
    answer: { accepted: true },
    expect: { deliveries },
    ...extra,
})

const answered = (
    seq: number,
    unitId: string,
    status = 200,
    kind: TruthRecord['kind'] = 'ses.send',
    actionId = 'email'
): TruthRecord => ({
    seq,
    at: new Date(FROM).toISOString(),
    kind,
    unitId,
    actionId,
    status,
    detail:
        kind === 'ses.feedback'
            ? { feedback: { snsMessageId: 'sns', sesMessageId: 'ses', bouncedRecipients: [] } }
            : {},
})

const counted = (partial: Partial<Counted> = {}): Counted => ({
    email_sent: 0,
    email_delivered: 0,
    email_bounced: 0,
    email_failed: 0,
    ...partial,
})

const evidence = (journal: JournalEntry[], truth: TruthRecord[], counters?: CounterReading): MeasureEvidence => ({
    journal,
    truth,
    fetchRetries: 3,
    samples: [],
    missed: [],
    host: [],
    writer: [],
    queue: [],
    sampledFrom: FROM,
    drive: { startedAt: FROM, endedAt: FROM + 60_000 },
    steps: [],
    timeline: [],
    counters,
})

const driftOf = (journal: JournalEntry[], truth: TruthRecord[], counters?: CounterReading): Record<string, unknown> =>
    Object.fromEntries(
        measure([{ name: 'counter_drift', params: {} }], evidence(journal, truth, counters)).map(({ key, value }) => [
            key,
            value,
        ])
    )

describe('counter drift', () => {
    const journal = [
        offered('run-1'),
        offered('run-2'),
        offered('run-3'),
        offered('run-4', ['webhook']),
        offered('run-5', ['email'], { answer: { accepted: false, status: 400 } }),
        offered('run-6', ['email'], { followUp: { accepted: true } }),
    ]
    const truth = [
        answered(1, 'run-1'),
        answered(2, 'run-2', 429),
        answered(3, 'run-2'),
        answered(4, 'run-2', 200, 'ses.feedback'),
        answered(5, 'run-3', 400),
        answered(6, 'run-4', 200, 'webhook', 'webhook'),
        answered(7, 'other-1'),
    ]

    it.each<[string, Counted, Record<string, number>]>([
        [
            'records zero drift when every counter saw what the sink saw',
            counted({ email_sent: 2, email_bounced: 1, email_failed: 1 }),
            { email_sent: 0, email_delivered: 0, email_bounced: 0, email_failed: 0 },
        ],
        [
            'records the sends a lost metrics flush never counted as negative drift',
            counted({ email_bounced: 1, email_failed: 1 }),
            { email_sent: -2, email_sent_counted: 0, email_sent_sink: 2 },
        ],
        [
            'records counts past the sink as positive drift',
            counted({ email_sent: 2, email_delivered: 3, email_bounced: 1, email_failed: 1 }),
            { email_delivered: 3, email_delivered_sink: 0 },
        ],
    ])('%s', (_name, read, expected) => {
        expect(driftOf(journal, truth, { counted: read })).toMatchObject({
            owed: 5,
            email_sent_events: null,
            email_sent_sink: 2,
            email_bounced_sink: 1,
            email_failed_sink: 1,
            ...expected,
        })
    })

    it.each<[string, CounterReading, string, RegExp]>([
        ['names the event count unmeasured on every read', { counted: counted() }, 'email_sent_events', /ingestion/],
        ['records why the counters could not be read', { unread: 'refused' }, 'email_sent', /^refused$/],
    ])('%s', (_name, counters, key, reason) => {
        expect(
            measure([{ name: 'counter_drift', params: {} }], evidence(journal, truth, counters)).find(
                (row) => row.key === key
            )
        ).toEqual({
            name: 'counter_drift',
            unit: 'messages',
            key,
            value: null,
            censored: true,
            unmeasured: expect.stringMatching(reason),
        })
    })

    it('records each counter as unknown when the counters could not be read', () => {
        expect(
            measure([{ name: 'counter_drift', params: {} }], evidence(journal, truth, { unread: 'refused' })).map(
                ({ key, value }) => [key, value]
            )
        ).toEqual(
            ['email_sent', 'email_delivered', 'email_bounced', 'email_failed', 'email_sent_events'].map((key) => [
                key,
                null,
            ])
        )
    })
})

describe('reading the counters', () => {
    const READ = { withinMs: 10_000, quietMs: 3000, pollMs: 1000 }
    const query = { teams: [7], from: FROM }

    const replay = (reads: (Counted | Error)[]): CounterProbe => {
        let next = 0
        return {
            counted: () => {
                const read = reads[Math.min(next++, reads.length - 1)]
                return read instanceof Error ? Promise.reject(read) : Promise.resolve(read)
            },
        }
    }

    it.each<[string, (Counted | Error)[], CounterReading]>([
        [
            'stops at the first read that matches the sink',
            [counted(), counted({ email_sent: 1 }), counted({ email_sent: 2 })],
            { counted: counted({ email_sent: 2 }) },
        ],
        [
            'settles on a short count once it stops changing',
            [counted(), counted({ email_sent: 1 })],
            { counted: counted({ email_sent: 1 }) },
        ],
        [
            'marks the count incomplete when it still changes at the bound',
            Array.from({ length: 20 }, (_, i) => counted({ email_failed: i })),
            { counted: counted({ email_failed: 10 }), incomplete: true },
        ],
        [
            'reports the last failure when no read ever succeeded',
            [new Error('ClickHouse answered the counter read with 404')],
            { unread: 'ClickHouse answered the counter read with 404' },
        ],
    ])('%s', async (_name, reads, expected) => {
        let clock = FROM
        const reading = await readCounters(replay(reads), query, counted({ email_sent: 2 }), READ, undefined, {
            now: () => clock,
            pause: (ms) => Promise.resolve((clock += ms)),
        })

        expect(reading).toEqual(expected)
    })
})
