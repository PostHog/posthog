import type { Step } from '../cards'
import type { TruthRecord } from '../provider-edge'
import { type JournalEntry, feedbackInFlightReasonOf } from './judge'
import { MeasureEvidence, measure } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')
const MINUTE = 60_000

const offered = (unitId: string): JournalEntry => ({
    unitId,
    kind: 'event',
    teamId: 7,
    offeredAt: FROM,
    answer: { accepted: true },
    expect: { deliveries: ['email'] },
})

let seq = 0

const posted = (unitId: string, postedAtMs: number, durationMs: number, status = 200): TruthRecord => ({
    seq: ++seq,
    at: new Date(FROM + postedAtMs + durationMs).toISOString(),
    kind: 'ses.feedback',
    unitId,
    status,
    detail: {
        feedback: {
            eventType: 'Delivery',
            snsMessageId: 'sns',
            sesMessageId: 'ses',
            postedAt: new Date(FROM + postedAtMs).toISOString(),
            durationMs,
        },
    },
})

const ramp: Step[] = [
    { scale: 1, fromMs: 0, toMs: MINUTE },
    { scale: 2, fromMs: MINUTE, toMs: 2 * MINUTE },
    { scale: 4, fromMs: 2 * MINUTE, toMs: 3 * MINUTE },
]

const evidence = (truth: TruthRecord[], judged: Partial<MeasureEvidence> = {}): MeasureEvidence => ({
    journal: ['run-1', 'run-2', 'run-3'].map(offered),
    truth,
    fetchRetries: 3,
    samples: [],
    missed: [],
    host: [],
    writer: [],
    queue: [],
    sampledFrom: FROM,
    truthFrom: 0,
    drive: { startedAt: FROM, endedAt: FROM + 2 * MINUTE },
    steps: ramp,
    timeline: [],
    ...judged,
})

const BOTH = [
    { name: 'ses_feedback_ms', params: {} },
    { name: 'ses_feedback_posts', params: {} },
]

const rowsOf = (truth: TruthRecord[], judged?: Partial<MeasureEvidence>): Record<string, unknown> =>
    Object.fromEntries(measure(BOTH, evidence(truth, judged)).map(({ name, key, value }) => [`${name}.${key}`, value]))

describe('SES feedback per ramp step', () => {
    const truth = [
        posted('run-1', 990, 10),
        posted('run-1', 1980, 20),
        posted('run-2', 2970, 30),
        posted('run-2', 3960, 40),
        posted('run-3', 4950, 50, 503),
        posted('run-3', 5940, 60, 400),
        posted('run-3', 7000, 0, 0),
        posted('run-1', MINUTE - 5, 10),
        posted('run-2', MINUTE, 0.4),
        posted('run-2', MINUTE + 995, 5),
        posted('run-3', MINUTE + 1995, 5),
        posted('run-1', 2 * MINUTE + 4993, 7),
        posted('other-1', 1000, 900),
        { ...posted('run-1', 1000, 0, 0), detail: { error: 'The send names no configuration set' } },
    ]

    it('measures each step from when its posts went out, giving later posts to the last step the drive reached', () => {
        expect(rowsOf(truth)).toEqual({
            'ses_feedback_ms.p50_1x': 30,
            'ses_feedback_ms.p99_1x': 60,
            'ses_feedback_ms.p50_2x': 5,
            'ses_feedback_ms.p99_2x': 7,
            'ses_feedback_posts.posted_1x': 8,
            'ses_feedback_posts.errors_1x': 2,
            'ses_feedback_posts.rejected_1x': 1,
            'ses_feedback_posts.posted_2x': 4,
            'ses_feedback_posts.errors_2x': 0,
            'ses_feedback_posts.rejected_2x': 0,
        })
    })

    it('takes p99 by nearest rank rather than the slowest post', () => {
        const hundred = Array.from({ length: 100 }, (_, index) => posted('run-1', 1000 + index, index + 1))

        expect(rowsOf(hundred)).toMatchObject({ 'ses_feedback_ms.p50_1x': 50, 'ses_feedback_ms.p99_1x': 99 })
    })

    it.each<[string, Partial<MeasureEvidence>, string]>([
        ['no SES feedback post went out', {}, 'no SES feedback post went out in this run'],
        [
            'SES feedback posts were still in flight at the final read',
            { feedbackInFlight: 2, unsettled: feedbackInFlightReasonOf(2) },
            'SES feedback posts were still in flight at the final read',
        ],
    ])('names every count unmeasured on a run where %s', (_story, judged, reason) => {
        const measured = measure([{ name: 'ses_feedback_posts', params: {} }], evidence([], judged))

        expect(measured.length).toBeGreaterThan(0)
        expect(
            measured.filter(
                ({ value, censored, unmeasured }) => value !== null || censored !== true || unmeasured !== reason
            )
        ).toEqual([])
    })

    it('gives no rows to a step with no window', () => {
        const steps: Step[] = [ramp[0], { scale: 3, fromMs: MINUTE, toMs: MINUTE }, ramp[1]]

        expect(Object.keys(rowsOf(truth, { steps })).filter((key) => key.endsWith('_3x'))).toEqual([])
    })

    it.each<[string, Partial<MeasureEvidence>]>([
        ['the run did not converge', { converged: false }],
        ['the truth never settled', { unsettled: 'the edge kept accepting sends' }],
        [
            'the run did not converge and the truth could not be read',
            { converged: false, unread: 'the edge answered 503' },
        ],
    ])('marks every row incomplete when %s, since posts may be missing', (_story, judged) => {
        const measured = measure(BOTH, evidence(truth, judged))

        expect(measured.length).toBeGreaterThan(0)
        expect(measured.filter(({ incomplete }) => incomplete !== true)).toEqual([])
    })

    it('censors the latency of a step where a post got no status, leaving that post out', () => {
        const measured = measure([{ name: 'ses_feedback_ms', params: {} }], evidence(truth))

        expect(measured.map(({ key, value, censored, unmeasured }) => ({ key, value, censored, unmeasured }))).toEqual([
            ...['p50_1x', 'p99_1x'].map((key) => ({
                key,
                value: key === 'p50_1x' ? 30 : 60,
                censored: true,
                unmeasured:
                    '1 SES feedback post in this step got no status or no whole answer, so its latency leaves it out',
            })),
            ...[
                ['p50_2x', 5],
                ['p99_2x', 7],
            ].map(([key, value]) => ({ key, value, censored: undefined, unmeasured: undefined })),
        ])
    })

    it('counts a rejection whose body could not be read and leaves its latency out', () => {
        const unread = posted('run-1', 2000, 5000, 429)
        unread.detail.feedback!.bodyUnread = true

        const measured = measure(BOTH, evidence([posted('run-1', 1000, 30), unread]))

        expect(
            measured
                .filter(({ key }) => key?.endsWith('_1x'))
                .map(({ name, key, value, censored, unmeasured }) => ({
                    row: `${name}.${key}`,
                    value,
                    censored,
                    unmeasured,
                }))
        ).toEqual([
            ...['p50_1x', 'p99_1x'].map((key) => ({
                row: `ses_feedback_ms.${key}`,
                value: 30,
                censored: true,
                unmeasured:
                    '1 SES feedback post in this step got no status or no whole answer, so its latency leaves it out',
            })),
            ...[
                ['posted_1x', 2],
                ['errors_1x', 0],
                ['rejected_1x', 1],
            ].map(([key, value]) => ({
                row: `ses_feedback_posts.${key}`,
                value,
                censored: undefined,
                unmeasured: undefined,
            })),
        ])
    })

    it('names the latency unmeasured for a step where no post got an answer', () => {
        const measured = measure(
            [{ name: 'ses_feedback_ms', params: {} }],
            evidence([posted('run-1', 1000, 5000, 0), posted('run-1', MINUTE + 1000, 5)])
        )

        expect(measured.filter(({ key }) => key?.endsWith('_1x'))).toEqual(
            ['p50_1x', 'p99_1x'].map((key) => ({
                name: 'ses_feedback_ms',
                unit: 'ms',
                key,
                value: null,
                censored: true,
                unmeasured: 'no SES feedback post in this step got an answer',
            }))
        )
    })

    it('names both measurements unmeasured when the truth could not be read', () => {
        expect(
            measure(
                [
                    { name: 'ses_feedback_ms', params: {} },
                    { name: 'ses_feedback_posts', params: {} },
                ],
                evidence([], { unread: 'the edge answered 503' })
            )
        ).toEqual(
            [
                ['ses_feedback_ms', 'ms'],
                ['ses_feedback_posts', 'posts'],
            ].map(([name, unit]) => ({
                name,
                unit,
                value: null,
                censored: true,
                unmeasured: 'the truth could not be read (the edge answered 503)',
            }))
        )
    })
})
