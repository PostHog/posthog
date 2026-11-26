import type { Counted, CounterProbe } from '../probe/counter-probe'
import type { TruthRecord } from '../provider-edge'
import { CounterReading, readCounters } from './drift'
import type { JournalEntry } from './judge'
import { MeasureEvidence, measure } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')
const HORIZON = FROM + 60_000

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
    actionId = 'email',
    flowId?: string
): TruthRecord => ({
    seq,
    at: new Date(FROM).toISOString(),
    kind,
    unitId,
    ...(kind !== 'ses.feedback' && { actionId }),
    flowId,
    status,
    detail:
        kind === 'ses.feedback'
            ? { feedback: { snsMessageId: 'sns', sesMessageId: 'ses', bouncedRecipients: ['bounced@example.com'] } }
            : status === 429
              ? { errorType: 'TooManyRequestsException' }
              : {},
})

const counted = (partial: Partial<Counted> = {}): Counted => ({
    email_sent: 0,
    email_delivered: 0,
    email_failed: 0,
    ...partial,
})

type Judged = Pick<MeasureEvidence, 'counters' | 'unread' | 'horizonAt' | 'converged' | 'unsettled'>

const evidence = (journal: JournalEntry[], truth: TruthRecord[], judged: Judged): MeasureEvidence => ({
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
    horizonAt: HORIZON,
    ...judged,
})

const rowsOf = (journal: JournalEntry[], truth: TruthRecord[], judged: Judged): ReturnType<typeof measure> =>
    measure([{ name: 'counter_drift', params: {} }], evidence(journal, truth, judged))

const driftOf = (journal: JournalEntry[], truth: TruthRecord[], judged: Judged): Record<string, unknown> =>
    Object.fromEntries(rowsOf(journal, truth, judged).map(({ key, value }) => [key, value]))

describe('counter drift', () => {
    const journal = [
        offered('run-1'),
        offered('run-2'),
        offered('run-3'),
        offered('run-4', ['webhook']),
        offered('run-5', ['email'], { answer: { accepted: false, status: 400 } }),
        offered('run-6', ['email'], { followUp: { accepted: true } }),
        offered('run-7'),
        offered('run-8'),
        offered('run-9', ['email'], { expect: { deliveries: ['email'], dueAt: HORIZON + 60_000 } }),
    ]
    const truth = [
        answered(1, 'run-1'),
        answered(2, 'run-2', 429),
        answered(3, 'run-2'),
        answered(4, 'run-2', 200, 'ses.feedback'),
        answered(5, 'run-3', 400),
        answered(6, 'run-4', 200, 'webhook', 'webhook'),
        answered(7, 'other-1'),
        answered(8, 'run-6', 200, 'ses.send', 'email', 'first-flow'),
        answered(9, 'run-6', 400, 'ses.send', 'email', 'follow-up-flow'),
        answered(10, 'run-7', 429),
        answered(11, 'run-8', 429),
    ]
    const sink = { owed: 7, email_sent_sink: 3, email_failed_sink: null }

    it.each<[string, Counted, Record<string, number | null>]>([
        [
            'records zero drift when every counter saw what the sink saw',
            counted({ email_sent: 3, email_failed: 2 }),
            { email_sent: 0, email_delivered: 0, email_failed: null, email_failed_counted: 2, email_bounced: null },
        ],
        [
            'records the sends a lost metrics flush never counted as negative drift',
            counted({ email_failed: 2 }),
            { email_sent: -3, email_sent_counted: 0 },
        ],
        [
            'records counts past the sink as positive drift',
            counted({ email_sent: 3, email_delivered: 3, email_failed: 2 }),
            { email_delivered: 3, email_delivered_sink: 0 },
        ],
    ])('%s', (_name, read, expected) => {
        expect(driftOf(journal, truth, { counters: { counted: read, consumers: 1 } })).toMatchObject({
            ...sink,
            email_sent_events: null,
            ...expected,
        })
    })

    it.each<[string, Judged, Record<string, number | null>]>([
        [
            'keeps the owed and sink counts when the counters could not be read',
            { counters: { unread: 'refused' } },
            { ...sink, email_sent: null, email_sent_counted: null },
        ],
        [
            'keeps what the counters showed when the truth could not be read',
            { counters: { counted: counted({ email_sent: 3 }), consumers: 1 }, unread: 'the edge answered 503' },
            { owed: 7, email_sent: null, email_sent_counted: 3, email_sent_sink: null },
        ],
        [
            'leaves the drift unknown when the run did not converge',
            { counters: { counted: counted({ email_sent: 4 }), consumers: 1 }, converged: false },
            { email_sent: null, email_sent_counted: 4, email_sent_sink: 3 },
        ],
        [
            'leaves the drift unknown when two Kafka tables feed the counters',
            { counters: { counted: counted({ email_sent: 6 }), consumers: 2 } },
            { email_sent: null, email_sent_counted: 6, email_sent_sink: 3 },
        ],
        [
            'leaves owed unknown when the run reached no recovery horizon',
            { counters: { counted: counted(), consumers: 1 }, horizonAt: undefined },
            { owed: null, email_sent_sink: 3 },
        ],
    ])('%s', (_name, judged, expected) => {
        expect(driftOf(journal, truth, judged)).toMatchObject(expected)
    })

    it.each<[string, Judged, string, RegExp]>([
        [
            'names the event count unmeasured on every read',
            { counters: { counted: counted(), consumers: 1 } },
            'email_sent_events',
            /ingestion/,
        ],
        [
            'names the bounce count unmeasured, since the edge records a bounce only after the webhook answers',
            { counters: { counted: counted(), consumers: 1 } },
            'email_bounced',
            /after the SES webhook answers/,
        ],
        [
            'records why the counters could not be read',
            { counters: { unread: 'refused' } },
            'email_sent_counted',
            /^refused$/,
        ],
        [
            'records why the drift is unknown when the run did not converge',
            { counters: { counted: counted(), consumers: 1 }, converged: false },
            'email_sent',
            /did not converge/,
        ],
        [
            'records why the drift is unknown when sends kept arriving through the final truth reads',
            { counters: { counted: counted(), consumers: 1 }, unsettled: 'the edge kept accepting sends' },
            'email_sent',
            /kept accepting sends/,
        ],
        [
            'records why the drift is unknown when two Kafka tables feed the counters',
            { counters: { counted: counted(), consumers: 2 } },
            'email_sent',
            /from 2 Kafka tables/,
        ],
        [
            'records why the drift is unknown when ClickHouse could not say what feeds the counters',
            { counters: { counted: counted(), consumersUnread: 'ClickHouse answered the consumer read with 503' } },
            'email_sent',
            /could not say how many Kafka tables feed app_metrics2 \(ClickHouse answered the consumer read with 503\)/,
        ],
        [
            'records why the truth could not be read',
            { counters: { counted: counted(), consumers: 1 }, unread: 'the edge answered 503' },
            'email_sent_sink',
            /the edge answered 503/,
        ],
    ])('%s', (_name, judged, key, reason) => {
        expect(rowsOf(journal, truth, judged).find((row) => row.key === key)).toEqual({
            name: 'counter_drift',
            unit: 'messages',
            key,
            value: null,
            censored: true,
            unmeasured: expect.stringMatching(reason),
        })
    })
})

describe('reading the counters', () => {
    const READ = { withinMs: 10_000, quietMs: 3000, pollMs: 1000 }
    const query = { teams: [7], from: FROM }

    const replay = (reads: (Counted | Error)[], consumers: number | Error): CounterProbe => {
        let next = 0
        return {
            counted: () => {
                const read = reads[Math.min(next++, reads.length - 1)]
                return read instanceof Error ? Promise.reject(read) : Promise.resolve(read)
            },
            consumers: () => (consumers instanceof Error ? Promise.reject(consumers) : Promise.resolve(consumers)),
        }
    }

    it.each<[string, (Counted | Error)[], CounterReading, number | Error]>([
        [
            'settles on the count once it stops changing',
            [counted(), counted({ email_sent: 1 })],
            { counted: counted({ email_sent: 1 }), consumers: 1 },
            1,
        ],
        [
            'keeps reading until late increments stop arriving',
            [2, 2, 3, 3, 4].map((sent) => counted({ email_sent: sent })),
            { counted: counted({ email_sent: 4 }), consumers: 1 },
            1,
        ],
        [
            'records how many Kafka tables feed the counters',
            [counted({ email_sent: 2 })],
            { counted: counted({ email_sent: 2 }), consumers: 2 },
            2,
        ],
        [
            'keeps why ClickHouse could not say which Kafka tables feed the counters',
            [counted({ email_sent: 2 })],
            { counted: counted({ email_sent: 2 }), consumersUnread: 'ClickHouse answered the consumer read with 503' },
            new Error('ClickHouse answered the consumer read with 503'),
        ],
        [
            'waits a full quiet window from the first read that succeeds after reads fail',
            [
                counted({ email_sent: 1 }),
                ...Array.from({ length: 2 }, () => new Error('ClickHouse answered the counter read with 503')),
                ...Array.from({ length: 3 }, () => counted({ email_sent: 1 })),
                counted({ email_sent: 2 }),
            ],
            { counted: counted({ email_sent: 2 }), consumers: 1 },
            1,
        ],
        [
            'marks the count incomplete when it still changes at the bound',
            Array.from({ length: 20 }, (_, i) => counted({ email_failed: i })),
            { counted: counted({ email_failed: 10 }), consumers: 1, incomplete: true },
            1,
        ],
        [
            'reports the last failure when no read ever succeeded',
            [new Error('ClickHouse answered the counter read with 404')],
            { unread: 'ClickHouse answered the counter read with 404' },
            1,
        ],
    ])('%s', async (_name, reads, expected, consumers) => {
        let clock = FROM
        const reading = await readCounters(replay(reads, consumers), query, READ, undefined, {
            now: () => clock,
            pause: (ms) => Promise.resolve((clock += ms)),
        })

        expect(reading).toEqual(expected)
    })
})
