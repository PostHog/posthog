import type { Step } from '../cards'
import type { TruthRecord } from '../provider-edge'
import type { JournalEntry } from './judge'
import { MeasureEvidence, MetricSample, MissedScrape, measure } from './measurements'

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

const posted = (unitId: string, answeredAtMs: number, durationMs: number, status = 200): TruthRecord => ({
    seq: ++seq,
    at: new Date(FROM + answeredAtMs).toISOString(),
    kind: 'ses.feedback',
    unitId,
    status,
    detail: { feedback: { eventType: 'Delivery', snsMessageId: 'sns', sesMessageId: 'ses', durationMs } },
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
    drive: { startedAt: FROM, endedAt: FROM + 2 * MINUTE },
    steps: ramp,
    timeline: [],
    ...judged,
})

const rowsOf = (truth: TruthRecord[], judged?: Partial<MeasureEvidence>): Record<string, unknown> =>
    Object.fromEntries(
        measure(
            [
                { name: 'ses_feedback_ms', params: {} },
                { name: 'ses_feedback_posts', params: {} },
            ],
            evidence(truth, judged)
        ).map(({ name, key, value }) => [`${name}.${key}`, value])
    )

describe('SES feedback per ramp step', () => {
    const truth = [
        posted('run-1', 1000, 10),
        posted('run-1', 2000, 20),
        posted('run-2', 3000, 30),
        posted('run-2', 4000, 40),
        posted('run-3', 5000, 50, 503),
        posted('run-3', 6000, 60, 400),
        posted('run-3', 7000, 0, 0),
        posted('run-1', MINUTE + 5, 10),
        posted('run-2', MINUTE + 1000, 5),
        posted('run-3', MINUTE + 2000, 5),
        posted('run-1', 2 * MINUTE + 5000, 7),
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
            'ses_feedback_posts.posted_2x': 3,
            'ses_feedback_posts.errors_2x': 0,
            'ses_feedback_posts.rejected_2x': 0,
        })
    })

    it('names the latency unmeasured for a step that posted nothing', () => {
        const measured = measure(
            [{ name: 'ses_feedback_ms', params: {} }],
            evidence([posted('run-1', MINUTE + 1000, 5)])
        )

        expect(measured.filter(({ key }) => key?.endsWith('_1x'))).toEqual(
            ['p50_1x', 'p99_1x'].map((key) => ({
                name: 'ses_feedback_ms',
                unit: 'ms',
                key,
                value: null,
                censored: true,
                unmeasured: 'the edge posted no SES feedback in this step',
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

describe('SES notifications lost', () => {
    const scraped = (
        role: string,
        atS: number,
        sesNotifications: Record<string, number>,
        startedAtS = -60
    ): MetricSample => ({
        role,
        replica: 0,
        at: FROM + atS * 1000,
        startedAt: FROM / 1000 + startedAtS,
        cpuSeconds: 1,
        rssBytes: 1,
        processed: {},
        pgClientErrors: 0,
        consumerLoopErrors: 0,
        janitorStalled: 0,
        lateness: {},
        sesNotifications,
    })

    const lostOf = (samples: MetricSample[], judged: Partial<MeasureEvidence> = {}): ReturnType<typeof measure> =>
        measure([{ name: 'ses_notifications_lost', params: {} }], evidence([], { samples, ...judged }))

    const run = [
        scraped('cdp-api', 0, { queued: 4 }),
        scraped('cdp-api', 60, { queued: 24 }),
        scraped('cdp-ses-webhooks', 0, { recorded: 3, skipped: 1 }),
        scraped('cdp-ses-webhooks', 60, { recorded: 19, skipped: 2, failed: 5, redelivered: 5 }),
    ]

    it('counts the notifications the webhook queued that the consumer neither recorded nor skipped', () => {
        expect(lostOf(run)).toEqual(
            Object.entries({ lost: 3, queued: 20, recorded: 16, skipped: 1 }).map(([key, value]) => ({
                name: 'ses_notifications_lost',
                unit: 'notifications',
                key,
                value,
            }))
        )
    })

    it.each<[string, MetricSample[], MissedScrape[]]>([
        ['a role restarted', [...run, scraped('cdp-ses-webhooks', 90, { recorded: 1 }, 80)], []],
        ['a scrape was missed after the last one', run, [{ role: 'cdp-api', replica: 0, at: FROM + 90_000 }]],
    ])('marks the count incomplete when %s', (_story, samples, missed) => {
        expect(lostOf(samples, { missed }).every(({ incomplete }) => incomplete === true)).toBe(true)
    })

    it('leaves the loss unknown when the run did not converge', () => {
        expect(lostOf(run, { converged: false }).find(({ key }) => key === 'lost')).toEqual({
            name: 'ses_notifications_lost',
            unit: 'notifications',
            key: 'lost',
            value: null,
            censored: true,
            unmeasured: 'the run did not converge, so the consumer may still have been recording',
        })
    })

    it('measures nothing on a run whose webhook queued no notification', () => {
        expect(lostOf([scraped('cdp-api', 0, {}), scraped('cdp-api', 60, {})])).toEqual([])
    })
})
