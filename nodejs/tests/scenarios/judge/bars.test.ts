import type { Named, Step } from '../cards'
import { BarEvidence, BarResult, CpuPoint, judgeBars } from './bars'
import type { JournalEntry } from './judge'
import type { HostSample, MetricSample } from './measurements'

const T = Date.UTC(2026, 0, 5, 10, 0, 0)
const MINUTE = 60_000
const STEPS: Step[] = [
    { scale: 1, fromMs: 0, toMs: MINUTE },
    { scale: 10, fromMs: MINUTE, toMs: 2 * MINUTE },
]
const BARS: Named[] = [
    { name: 'writer_cpu_under', params: { percent: 70 } },
    { name: 'pickup_p99_under', params: { seconds: 5, queues: ['hogflow', 'email'] } },
]
const LE = ['1', '5', '10', '+Inf']

const iso = (atS: number): string => new Date(T + atS * 1000).toISOString()

const times = (count: number, lateSeconds: number): number[] => Array<number>(Math.max(count, 0)).fill(lateSeconds)

const pickedUp = (...lateSeconds: number[]): Record<string, number> =>
    Object.fromEntries(LE.map((le) => [le, lateSeconds.filter((late) => le === '+Inf' || late <= Number(le)).length]))

type Picks = Record<string, number[]>

const scrapedEvery5s = (
    untilS: number,
    picksAt: (atS: number) => Picks,
    {
        startedAtS = () => -60,
        queues = ['hogflow', 'email'],
        offsetS = 0,
    }: { startedAtS?: (atS: number) => number; queues?: string[]; offsetS?: number } = {}
): MetricSample[] =>
    Array.from({ length: untilS / 5 + 1 }, (_, i) => i * 5 + offsetS).flatMap((atS) =>
        queues.map((queue) => ({
            role: `cdp-cyclotron-worker-${queue}`,
            replica: 0,
            at: T + atS * 1000,
            startedAt: T / 1000 + startedAtS(atS),
            cpuSeconds: 1,
            rssBytes: 1,
            processed: {},
            pgClientErrors: 0,
            consumerLoopErrors: 0,
            janitorStalled: 0,
            lateness: Object.fromEntries(
                Object.entries(picksAt(atS))
                    .filter(([picked]) => picked === queue)
                    .map(([picked, late]) => [picked, pickedUp(...late)])
            ),
        }))
    )

const prompt = (atS: number): Picks => ({ hogflow: times(atS, 0.5), email: times(atS, 0.5) })

const lateAfter = (queue: string, fromS: number) => (atS: number) => ({
    ...prompt(atS),
    [queue]: [...times(Math.min(atS, fromS), 0.5), ...times(atS - fromS, 8)],
})

const offeredAtRates = (...perSecond: number[]): JournalEntry[] =>
    perSecond.flatMap((rate, step) =>
        Array.from({ length: rate * 60 }, (_, i) => ({
            unitId: `run-${step}-${i}`,
            kind: 'transactional' as const,
            teamId: 7,
            offeredAt: T + step * MINUTE + (i * 1000) / rate,
            answer: i % 2 === 0 || step === 0 ? { accepted: true } : { accepted: false, status: 503 },
            expect: { deliveries: ['email'] },
        }))
    )

const cpu = (percentByMinute: Record<number, number>): CpuPoint[] =>
    Object.entries(percentByMinute).map(([minute, percent]) => ({ at: T + Number(minute) * MINUTE, percent }))

const hostBusy = (inFirstStep: number, inSecondStep: number): HostSample[] =>
    Array.from({ length: 25 }, (_, i) => i * 5).map((atS) => ({
        at: T + atS * 1000,
        busyTicks: Math.min(atS, 60) * 100 * inFirstStep + Math.max(atS - 60, 0) * 100 * inSecondStep,
        totalTicks: atS * 100,
    }))

const evidence = (changes: Partial<BarEvidence>): BarEvidence => ({
    journal: offeredAtRates(1, 10),
    samples: scrapedEvery5s(120, prompt),
    drive: { startedAt: T, endedAt: T + 2 * MINUTE },
    steps: STEPS,
    writerCpu: cpu({ 0: 40, 1: 65 }),
    host: [],
    ...changes,
})

const HELD: BarResult[] = [
    { name: 'writer_cpu_under', unit: '%', passed: true },
    { name: 'pickup_p99_under', unit: 's', passed: true },
]

const broke = (bar: 0 | 1, scale: number, atS: number, value: number, key?: string, offered = scale): BarResult => ({
    ...HELD[bar],
    passed: false,
    breakingPoint: { scale, at: iso(atS), offeredPerSecond: offered, ...(key && { key }), value },
})

const unjudged = (bar: 0 | 1, why: string): BarResult => ({ ...HELD[bar], passed: false, unjudged: why })

describe('judgeBars', () => {
    it.each<[string, Partial<BarEvidence>, BarResult[]]>([
        ['every step stayed under both bars', {}, HELD],
        [
            'the writer CPU crossed its bar at the 10x step, counting refused units as offered',
            { writerCpu: cpu({ 0: 40, 1: 85 }) },
            [broke(0, 10, 60, 85), HELD[1]],
        ],
        [
            'the writer CPU crossed its bar at the 10x step, leaving out the events Kafka refused',
            {
                journal: offeredAtRates(1, 10).map((entry) => ({ ...entry, kind: 'event' as const })),
                writerCpu: cpu({ 0: 40, 1: 85 }),
            },
            [broke(0, 10, 60, 85, undefined, 5), HELD[1]],
        ],
        [
            'the writer CPU was over its bar from the 1x step on, so the first step names the breaking point',
            { writerCpu: cpu({ 0: 90, 1: 95 }) },
            [broke(0, 1, 0, 90), HELD[1]],
        ],
        [
            'a CPU minute that straddles a step boundary counts in neither step',
            {
                drive: { startedAt: T + 30_000, endedAt: T + 270_000 },
                steps: [
                    { scale: 1, fromMs: 0, toMs: 2 * MINUTE },
                    { scale: 10, fromMs: 2 * MINUTE, toMs: 4 * MINUTE },
                ],
                writerCpu: cpu({ 1: 40, 2: 90, 3: 90 }),
                samples: scrapedEvery5s(270, prompt),
                journal: [],
            },
            [
                {
                    ...HELD[0],
                    passed: false,
                    breakingPoint: { scale: 10, at: iso(150), offeredPerSecond: 0, value: 90 },
                },
                HELD[1],
            ],
        ],
        [
            'CloudWatch returned no reading for a minute of the 10x step',
            { writerCpu: cpu({ 0: 40 }) },
            [unjudged(0, `no writer CPU reading for the minute at ${iso(60)} in the 10x step`), HELD[1]],
        ],
        [
            'the writer CPU could not be read off a run host',
            { writerCpu: { unread: 'no writer CPU reading off a run host' } },
            [unjudged(0, 'no writer CPU reading off a run host in the 1x step'), HELD[1]],
        ],
        [
            'one queue picked up late at the 10x step while the other stayed prompt',
            { samples: scrapedEvery5s(120, lateAfter('hogflow', 60)) },
            [HELD[0], broke(1, 10, 60, 10, 'hogflow')],
        ],
        [
            'one queue stopped picking up at the 10x step while the other stayed prompt',
            { samples: scrapedEvery5s(120, (atS) => ({ ...prompt(atS), email: times(Math.min(atS, 60), 0.5) })) },
            [HELD[0], broke(1, 10, 60, 60, 'email')],
        ],
        [
            'a worker picked up late, restarted inside the 10x step, then picked up promptly',
            {
                samples: scrapedEvery5s(
                    120,
                    (atS) =>
                        atS <= 90
                            ? lateAfter('email', 60)(atS)
                            : { hogflow: times(atS - 90, 0.5), email: times(atS - 90, 0.5) },
                    { startedAtS: (atS) => (atS <= 90 ? -60 : 90) }
                ),
            },
            [HELD[0], broke(1, 10, 60, 10, 'email')],
        ],
        [
            'one queue picked up later than the histogram reaches, so the largest bucket bounds the value',
            {
                samples: scrapedEvery5s(120, (atS) => ({
                    ...prompt(atS),
                    email: [...times(Math.min(atS, 60), 0.5), ...times(atS - 60, 600)],
                })),
            },
            [HELD[0], broke(1, 10, 60, 10, 'email')],
        ],
        [
            'a scrape after the step boundary reported late pickups from the end of the 1x step',
            {
                samples: scrapedEvery5s(
                    120,
                    (atS) => ({ ...prompt(atS), email: [...times(atS, 0.5), ...times(atS >= 62 ? 5 : 0, 8)] }),
                    { offsetS: -3 }
                ),
            },
            [HELD[0], broke(1, 1, 0, 10, 'email')],
        ],
        [
            'jobs due in the 10x step were picked up late after the drive ended',
            { samples: scrapedEvery5s(150, lateAfter('hogflow', 120)) },
            [HELD[0], broke(1, 10, 60, 10, 'hogflow')],
        ],
        [
            'the worker metrics stopped answering early in the 10x step',
            { samples: scrapedEvery5s(65, prompt) },
            [HELD[0], unjudged(1, `no metrics from cdp-cyclotron-worker-hogflow-0 after ${iso(65)} in the 10x step`)],
        ],
        [
            'the email worker stopped answering before its first pickup while the hogflow worker kept picking up',
            {
                samples: [
                    ...scrapedEvery5s(120, prompt, { queues: ['hogflow'] }),
                    ...scrapedEvery5s(30, () => ({}), { queues: ['email'] }),
                ],
            },
            [HELD[0], unjudged(1, `no metrics from cdp-cyclotron-worker-email-0 after ${iso(30)} in the 1x step`)],
        ],
        [
            'the email worker was never scraped',
            { samples: scrapedEvery5s(120, prompt, { queues: ['hogflow'] }) },
            [HELD[0], unjudged(1, 'no metrics from cdp-cyclotron-worker-email in the 1x step')],
        ],
        [
            'the run host reached its CPU ceiling in the 10x step, so the writer CPU there is not judged',
            { host: hostBusy(0.4, 0.95), hostCpuCeiling: 0.95, writerCpu: cpu({ 0: 40, 1: 85 }) },
            [
                unjudged(0, 'the run host was 95% busy in the 10x step, at or over the 95% ceiling'),
                unjudged(1, 'the run host was 95% busy in the 10x step, at or over the 95% ceiling'),
            ],
        ],
        [
            'the run host was over its CPU ceiling from the 1x step on, so no later step is read',
            { host: hostBusy(0.95, 0.4), hostCpuCeiling: 0.9, writerCpu: cpu({ 0: 40, 1: 85 }) },
            [
                unjudged(0, 'the run host was 95% busy in the 1x step, at or over the 90% ceiling'),
                unjudged(1, 'the run host was 95% busy in the 1x step, at or over the 90% ceiling'),
            ],
        ],
        [
            'a bar broke in the 1x step before the run host went over its CPU ceiling in the 10x step',
            { host: hostBusy(0.4, 0.95), hostCpuCeiling: 0.9, writerCpu: cpu({ 0: 90, 1: 95 }) },
            [broke(0, 1, 0, 90), unjudged(1, 'the run host was 95% busy in the 10x step, at or over the 90% ceiling')],
        ],
        [
            'a busy run host is not judged without a CPU ceiling in the profile',
            { host: hostBusy(0.4, 0.95), writerCpu: cpu({ 0: 40, 1: 85 }) },
            [broke(0, 10, 60, 85), HELD[1]],
        ],
        [
            'fewer than two host CPU samples fall in a step while the profile sets a CPU ceiling',
            { hostCpuCeiling: 0.9 },
            [
                unjudged(0, 'fewer than two host CPU samples in the 1x step'),
                unjudged(1, 'fewer than two host CPU samples in the 1x step'),
            ],
        ],
        [
            'the drive was interrupted before its 10x step',
            { drive: { startedAt: T, endedAt: T + MINUTE } },
            [unjudged(0, 'the drive ended before the 10x step'), unjudged(1, 'the drive ended before the 10x step')],
        ],
    ])('%s', (_story, changes, expected) => {
        expect(judgeBars(BARS, evidence(changes))).toEqual(expected)
    })

    it.each<[string, number, BarResult]>([
        ['breaks a bar at the largest bucket when pickups overflow it', 10, broke(1, 10, 60, 10, 'email')],
        [
            'leaves a bar above the largest bucket unjudged when pickups overflow it',
            20,
            unjudged(1, "the email p99 is past the histogram's largest bucket of 10 s in the 10x step"),
        ],
    ])('%s', (_story, seconds, expected) => {
        const overflowing = evidence({
            samples: scrapedEvery5s(120, (atS) => ({
                ...prompt(atS),
                email: [...times(Math.min(atS, 60), 0.5), ...times(atS - 60, 600)],
            })),
        })

        const [, pickup] = judgeBars([BARS[0], { ...BARS[1], params: { ...BARS[1].params, seconds } }], overflowing)

        expect(pickup).toEqual(expected)
    })
})
