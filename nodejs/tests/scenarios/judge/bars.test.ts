import type { Named, Step } from '../cards'
import { BarEvidence, BarResult, CpuPoint, judgeBars } from './bars'
import type { JournalEntry } from './judge'
import type { MetricSample } from './measurements'

const T = Date.UTC(2026, 0, 5, 10, 0, 0)
const MINUTE = 60_000
const STEPS: Step[] = [
    { scale: 1, fromMs: 0, toMs: MINUTE },
    { scale: 10, fromMs: MINUTE, toMs: 2 * MINUTE },
]
const BARS: Named[] = [
    { name: 'writer_cpu_under', params: { percent: 70 } },
    { name: 'pickup_p99_under', params: { seconds: 5 } },
]
const LE = ['1', '5', '10', '+Inf']

const pickedUp = (...lateSeconds: number[]): Record<string, number> =>
    Object.fromEntries(LE.map((le) => [le, lateSeconds.filter((late) => le === '+Inf' || late <= Number(le)).length]))

const times = (count: number, lateSeconds: number): number[] => Array<number>(count).fill(lateSeconds)

const scraped = (
    atS: number,
    lateness: MetricSample['lateness'],
    { replica = 0, startedAtS = -60 } = {}
): MetricSample => ({
    role: 'cdp-cyclotron-worker',
    replica,
    at: T + atS * 1000,
    startedAt: T / 1000 + startedAtS,
    cpuSeconds: 1,
    rssBytes: 1,
    processed: {},
    pgClientErrors: 0,
    consumerLoopErrors: 0,
    lateness,
})

const offeredAtRates = (...perSecond: number[]): JournalEntry[] =>
    perSecond.flatMap((rate, step) =>
        Array.from({ length: rate * 60 }, (_, i) => ({
            unitId: `run-${step}-${i}`,
            kind: 'event' as const,
            teamId: 7,
            offeredAt: T + step * MINUTE + (i * 1000) / rate,
            answer: { accepted: true },
            expect: { deliveries: ['email'] },
        }))
    )

const PROMPT_PICKUPS = [
    scraped(0, {}),
    scraped(60, { email: pickedUp(...times(100, 0.5)), hogflow: pickedUp(...times(100, 0.5)) }),
    scraped(120, { email: pickedUp(...times(200, 0.5)), hogflow: pickedUp(...times(200, 0.5)) }),
]

const CPU = (...percent: number[]): CpuPoint[] =>
    percent.map((value, minute) => ({ at: T + minute * MINUTE, percent: value }))

const evidence = (changes: Partial<BarEvidence>): BarEvidence => ({
    journal: offeredAtRates(1, 10),
    samples: PROMPT_PICKUPS,
    drive: { startedAt: T, endedAt: T + 2 * MINUTE },
    steps: STEPS,
    writerCpu: CPU(40, 65),
    ...changes,
})

const HELD: BarResult[] = [
    { name: 'writer_cpu_under', unit: '%', passed: true },
    { name: 'pickup_p99_under', unit: 's', passed: true },
]

describe('judgeBars', () => {
    it.each<[string, Partial<BarEvidence>, BarResult[]]>([
        ['every step stayed under both bars', {}, HELD],
        [
            'the writer CPU crossed its bar at the 10x step while pickups stayed prompt',
            { writerCpu: CPU(40, 85) },
            [
                {
                    ...HELD[0],
                    passed: false,
                    breakingPoint: {
                        scale: 10,
                        at: new Date(T + MINUTE).toISOString(),
                        offeredPerSecond: 10,
                        value: 85,
                    },
                },
                HELD[1],
            ],
        ],
        [
            'one queue picked up late at the 10x step while the writer CPU stayed under its bar',
            {
                samples: [
                    ...PROMPT_PICKUPS.slice(0, 2),
                    scraped(120, {
                        email: pickedUp(...times(200, 0.5)),
                        hogflow: pickedUp(...times(100, 0.5), ...times(100, 8)),
                    }),
                ],
            },
            [
                HELD[0],
                {
                    ...HELD[1],
                    passed: false,
                    breakingPoint: {
                        scale: 10,
                        at: new Date(T + MINUTE).toISOString(),
                        offeredPerSecond: 10,
                        key: 'hogflow',
                        value: 10,
                    },
                },
            ],
        ],
        [
            'the writer CPU was over its bar from the 1x step on, so the first step names the breaking point',
            { writerCpu: CPU(90, 95) },
            [
                {
                    ...HELD[0],
                    passed: false,
                    breakingPoint: { scale: 1, at: new Date(T).toISOString(), offeredPerSecond: 1, value: 90 },
                },
                HELD[1],
            ],
        ],
        [
            'a worker restarted inside the 10x step and picked up late after it',
            {
                samples: [
                    ...PROMPT_PICKUPS.slice(0, 2),
                    scraped(120, { email: pickedUp(...times(50, 8)) }, { startedAtS: 90 }),
                ],
            },
            [
                HELD[0],
                {
                    ...HELD[1],
                    passed: false,
                    breakingPoint: {
                        scale: 10,
                        at: new Date(T + MINUTE).toISOString(),
                        offeredPerSecond: 10,
                        key: 'email',
                        value: 10,
                    },
                },
            ],
        ],
        [
            'the writer CPU could not be read off a run host',
            { writerCpu: { unread: 'no writer CPU reading off a run host' } },
            [
                {
                    ...HELD[0],
                    passed: false,
                    unjudged: 'no writer CPU reading off a run host in the 1x step',
                },
                HELD[1],
            ],
        ],
        [
            'the drive was interrupted before its 10x step',
            { drive: { startedAt: T, endedAt: T + MINUTE } },
            [
                { ...HELD[0], passed: false, unjudged: 'the drive ended before the 10x step' },
                { ...HELD[1], passed: false, unjudged: 'the drive ended before the 10x step' },
            ],
        ],
        [
            'no worker picked up a job in the 10x step',
            { samples: PROMPT_PICKUPS.slice(0, 2) },
            [HELD[0], { ...HELD[1], passed: false, unjudged: 'no job pickup in the 10x step' }],
        ],
    ])('%s', (_story, changes, expected) => {
        expect(judgeBars(BARS, evidence(changes))).toEqual(expected)
    })
})
