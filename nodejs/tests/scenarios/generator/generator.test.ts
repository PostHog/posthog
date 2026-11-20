import { execFile } from 'child_process'
import http from 'http'
import { AddressInfo } from 'net'
import path from 'path'

import { LoadedCard, load, stepsOf } from '../cards'
import type { JournalEntry } from '../judge/judge'
import { type LiveRamp, rampOf, watchRamp } from '../judge/ramp'
import { SeedState, StepGate, drive } from './generator'
import { OfferContext, kafkaEmit } from './traffic'

const SMOKE = load(path.join(__dirname, '..', 'cards', 'smoke.yaml'))
const NEVER_ABORTED = new AbortController().signal
const CDP_API = { url: 'http://127.0.0.1:1', jwt: { mint: () => 'unused' } }
const NO_FEEDBACK: OfferContext['sesFeedback'] = { settled: () => Promise.reject(new Error('no follow-up expected')) }

const seededFor = (teamIds: number[], traffic: string): SeedState => ({
    teamIds,
    flowIds: Object.fromEntries(
        [traffic, `${traffic}.followup`].map((key) => [
            key,
            Object.fromEntries(teamIds.map((teamId) => [teamId, `${key}-${teamId}`])),
        ])
    ),
})

type Produce = Parameters<typeof kafkaEmit>[0]['produce']
type Summary = Awaited<ReturnType<typeof drive>>

function cardWith({
    seed = 1,
    ratePerSecond,
    driveFor,
    traffic = 'event_email',
}: {
    seed?: number
    ratePerSecond: number
    driveFor: string
    traffic?: string
}) {
    return {
        ...SMOKE,
        card: {
            ...SMOKE.card,
            seed,
            drive: { ...SMOKE.card.drive, for: driveFor, traffic: [{ name: traffic, params: {} }] },
        },
        profile: { ...SMOKE.profile, traffic: { [traffic]: { ratePerSecond } } },
    } satisfies LoadedCard
}

function rampedCard(
    ratePerSecond: number,
    ramp: NonNullable<LoadedCard['card']['drive']['ramp']>,
    driveFor: string,
    stopOnBreak?: true
): LoadedCard {
    const plain = cardWith({ ratePerSecond, driveFor })
    return { ...plain, card: { ...plain.card, drive: { ...plain.card.drive, ramp, stopOnBreak } } }
}

function startDrive(
    loaded: LoadedCard,
    produce: Produce,
    {
        teamIds = [7],
        signal = NEVER_ABORTED,
        cdpApi = CDP_API,
        sesFeedback = NO_FEEDBACK,
        halt,
        gate,
    }: {
        teamIds?: number[]
        signal?: AbortSignal
        halt?: AbortSignal
        gate?: StepGate
        cdpApi?: OfferContext['cdpApi']
        sesFeedback?: OfferContext['sesFeedback']
    } = {}
): { driving: Promise<Summary>; journal: JournalEntry[] } {
    const journal: JournalEntry[] = []
    const seeded = seededFor(teamIds, loaded.card.drive.traffic[0].name)
    const driving = drive(loaded, seeded, { record: (entry) => journal.push(entry) }, signal, {
        emit: kafkaEmit({ produce }, 'scenario_events_test'),
        cdpApi,
        sesFeedback,
        runId: 'run-a',
        halt,
        gate,
    })
    return { driving, journal }
}

function heldKafka() {
    const held: { resolve(): void; reject(error: Error): void }[] = []
    return {
        produce: (() => new Promise<void>((resolve, reject) => held.push({ resolve, reject }))) satisfies Produce,
        acknowledge: (count = held.length) => held.splice(0, count).forEach(({ resolve }) => resolve()),
        reject: () => held.splice(0).forEach(({ reject }) => reject(new Error('broker down'))),
    }
}

describe('drive', () => {
    const ACKNOWLEDGED: Produce = () => Promise.resolve()

    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each<[string, number, (kafka: ReturnType<typeof heldKafka>) => void, Partial<Summary>]>([
        [
            'every produce acknowledged',
            100,
            (kafka) => kafka.acknowledge(),
            { targetUnits: 5, offeredUnits: 5, steps: [expect.objectContaining({ offeredUnits: 5 })] },
        ],
        ['every produce rejected', 100, (kafka) => kafka.reject(), { targetUnits: 5, offeredUnits: 0 }],
        [
            'every produce acknowledged after the window',
            101,
            (kafka) => kafka.acknowledge(),
            { targetUnits: 5, offeredUnits: 0, steps: [expect.objectContaining({ offeredUnits: 0 })] },
        ],
    ])(
        'counts a unit as offered once Kafka acknowledged it inside the window: %s',
        async (_story, answeredAtMs, answer, expected) => {
            const kafka = heldKafka()
            const { driving } = startDrive(cardWith({ ratePerSecond: 50, driveFor: '100ms' }), kafka.produce)

            await jest.advanceTimersByTimeAsync(answeredAtMs)
            answer(kafka)

            expect(await driving).toMatchObject(expected)
        }
    )

    it.each(['transactional_email', 'bounce_followup'])(
        'refuses %s before its first offer on a run target without the local CDP API and SES feedback',
        async (traffic) => {
            const loaded = cardWith({ ratePerSecond: 50, driveFor: '100ms', traffic })
            const emitted: string[] = []
            const journal: JournalEntry[] = []

            await expect(
                drive(loaded, seededFor([7], traffic), { record: (entry) => journal.push(entry) }, NEVER_ABORTED, {
                    emit: (unit) => {
                        emitted.push(unit.unitId)
                        return Promise.resolve({ accepted: true })
                    },
                    runId: 'run-a',
                })
            ).rejects.toThrow(`${traffic} needs the local CDP API and SES feedback`)
            expect({ emitted, journal }).toEqual({ emitted: [], journal: [] })
        }
    )

    it('counts no acknowledgement that arrived after the drive was due to end, though its last timer woke late', async () => {
        const kafka = heldKafka()
        const startedAt = Date.now()
        const { driving } = startDrive(cardWith({ ratePerSecond: 50, driveFor: '100ms' }), kafka.produce)

        await jest.advanceTimersByTimeAsync(90)
        jest.setSystemTime(startedAt + 150)
        kafka.acknowledge()
        await jest.advanceTimersByTimeAsync(10)

        expect(await driving).toMatchObject({
            targetUnits: 5,
            offeredUnits: 0,
            steps: [expect.objectContaining({ dueUnits: 5, offeredUnits: 0 })],
        })
    })

    it.each<[string, Produce, object]>([
        [
            'its first send was accepted',
            () => Promise.resolve(),
            {
                journal: [{ unitId: 'run-a-1', answer: { accepted: true }, followUp: { notSent: 'no feedback' } }],
                summary: { targetUnits: 1, offeredUnits: 1 },
            },
        ],
        [
            'its first send was refused',
            () => Promise.reject(new Error('broker down')),
            {
                journal: [{ unitId: 'run-a-1', answer: { accepted: false }, followUp: undefined }],
                summary: { targetUnits: 1, offeredUnits: 0 },
            },
        ],
    ])(
        'journals a follow-up after the window with the unit, and counts it by its first answer, once %s',
        async (_story, produce, expected) => {
            const sesFeedback = {
                settled: () => new Promise<string>((resolve) => setTimeout(() => resolve('no feedback'), 5000)),
            }
            const { driving, journal } = startDrive(
                cardWith({ ratePerSecond: 10, driveFor: '100ms', traffic: 'bounce_followup' }),
                produce,
                { sesFeedback }
            )

            await jest.advanceTimersByTimeAsync(5000)

            expect({
                summary: await driving,
                journal: journal.map(({ unitId, answer, followUp }) => ({ unitId, answer, followUp })),
            }).toMatchObject(expected)
        }
    )

    it.each<[string, (interrupt: AbortController) => void, string | undefined, string]>([
        ['an interrupt', (interrupt) => interrupt.abort(), undefined, 'summary: 2 targeted, 0 offered'],
        ['another follow-up failing', () => undefined, 'run-a-1', 'Error: the edge is down'],
    ])(
        'sends no follow-up once %s stopped the drive, and ends only after the follow-ups it waited on settled',
        async (_story, stop, failingUnit, expected) => {
            jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
            let followUpsSent = 0
            const server = http.createServer((request, response) => {
                followUpsSent += 1
                request.resume()
                response.writeHead(422).end(JSON.stringify({ error: 'recipient_suppressed' }))
            })
            await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
            const { port } = server.address() as AddressInfo
            const interrupt = new AbortController()
            const settled = (unitId: string): Promise<string | undefined> =>
                unitId === failingUnit
                    ? new Promise((_resolve, reject) => setTimeout(() => reject(new Error('the edge is down')), 60))
                    : new Promise((resolve) => setTimeout(() => resolve(undefined), 1000))
            try {
                const { driving, journal } = startDrive(
                    cardWith({ ratePerSecond: 20, driveFor: '100ms', traffic: 'bounce_followup' }),
                    ACKNOWLEDGED,
                    {
                        signal: interrupt.signal,
                        cdpApi: { ...CDP_API, url: `http://127.0.0.1:${port}` },
                        sesFeedback: { settled },
                    }
                )
                let outcome: string | undefined
                void driving.then(
                    ({ targetUnits, offeredUnits }) =>
                        (outcome = `summary: ${targetUnits} targeted, ${offeredUnits} offered`),
                    (error: unknown) => (outcome = String(error))
                )

                await jest.advanceTimersByTimeAsync(70)
                stop(interrupt)
                await jest.advanceTimersByTimeAsync(979)
                const beforeTheFollowUpsSettled = outcome
                await jest.advanceTimersByTimeAsync(1)
                await driving.catch(() => undefined)

                expect({ beforeTheFollowUpsSettled, outcome, followUpsSent, journal }).toEqual({
                    beforeTheFollowUpsSettled: undefined,
                    outcome: expected,
                    followUpsSent: 0,
                    journal: [],
                })
            } finally {
                server.closeAllConnections()
                await new Promise<void>((resolve) => server.close(() => resolve()))
            }
        }
    )

    it.each([
        ['accepted', 202],
        ['refused', 503],
    ])('counts a transactional unit sent inside the window that cdp-api %s after the window', async (_, status) => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        const held: http.ServerResponse[] = []
        let arrive = (): void => undefined
        const arrived = new Promise<void>((resolve) => (arrive = resolve))
        const server = http.createServer((request, response) => {
            request.resume()
            held.push(response)
            if (held.length === 2) {
                arrive()
            }
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const { port } = server.address() as AddressInfo
        const loaded = cardWith({ ratePerSecond: 20, driveFor: '100ms' })
        const transactional = {
            ...loaded,
            card: {
                ...loaded.card,
                drive: { ...loaded.card.drive, traffic: [{ name: 'transactional_email', params: {} }] },
            },
            profile: { ...loaded.profile, traffic: { transactional_email: { ratePerSecond: 20 } } },
        } satisfies LoadedCard
        try {
            const { driving } = startDrive(transactional, ACKNOWLEDGED, {
                cdpApi: { ...CDP_API, url: `http://127.0.0.1:${port}` },
            })

            await jest.advanceTimersByTimeAsync(50)
            await arrived
            await jest.advanceTimersByTimeAsync(100)
            held.forEach((response) => response.writeHead(status).end('{}'))

            expect(await driving).toMatchObject({ targetUnits: 2, offeredUnits: 2 })
        } finally {
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        }
    })

    it('counts a transactional unit for the gate of a step that stops on a break once it was sent, before cdp-api answers', async () => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        const held: http.ServerResponse[] = []
        let arrive = (): void => undefined
        const arrived = new Promise<void>((resolve) => (arrive = resolve))
        const server = http.createServer((request, response) => {
            request.resume()
            if (held.length === 2) {
                response.writeHead(202).end('{}')
                return
            }
            held.push(response)
            if (held.length === 2) {
                arrive()
            }
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const { port } = server.address() as AddressInfo
        const loaded = rampedCard(
            20,
            [
                { scale: 1, for: '100ms' },
                { scale: 2, for: '100ms' },
            ],
            '200ms',
            true
        )
        const transactional = {
            ...loaded,
            card: {
                ...loaded.card,
                drive: { ...loaded.card.drive, traffic: [{ name: 'transactional_email', params: {} }] },
            },
            profile: { ...loaded.profile, traffic: { transactional_email: { ratePerSecond: 20 } } },
        } satisfies LoadedCard
        let offered = (): number => -1
        const gate: StepGate = (_step, offeredSoFar) => {
            offered = offeredSoFar
            return Promise.resolve()
        }
        try {
            const { driving } = startDrive(transactional, ACKNOWLEDGED, {
                cdpApi: { ...CDP_API, url: `http://127.0.0.1:${port}` },
                gate,
            })

            await jest.advanceTimersByTimeAsync(50)
            await arrived
            await jest.advanceTimersByTimeAsync(60)
            const live = offered()
            held.forEach((response) => response.writeHead(202).end('{}'))
            await jest.advanceTimersByTimeAsync(200)

            expect({ live, summary: await driving }).toMatchObject({ live: 2, summary: { offeredUnits: 6 } })
        } finally {
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        }
    })

    it('stops waiting for acknowledgements on an interrupt and leaves the pending units out of the summary and the journal', async () => {
        const kafka = heldKafka()
        const interrupt = new AbortController()
        const { driving, journal } = startDrive(cardWith({ ratePerSecond: 50, driveFor: '100ms' }), kafka.produce, {
            signal: interrupt.signal,
        })

        await jest.advanceTimersByTimeAsync(100)
        kafka.acknowledge(2)
        await jest.advanceTimersByTimeAsync(0)
        interrupt.abort()
        const summary = await driving
        kafka.acknowledge()
        await jest.advanceTimersByTimeAsync(0)

        expect({ summary, journaled: journal.map(({ unitId }) => unitId) }).toMatchObject({
            summary: { targetUnits: 5, offeredUnits: 2 },
            journaled: ['run-a-1', 'run-a-2'],
        })
    })

    it.each([
        ['between two units', 450],
        ['in the millisecond its last unit was offered', 400],
    ])(
        'stops offering at a halt %s, still journals the units in flight, and counts only the units due before it',
        async (_story, haltAtMs) => {
            const kafka = heldKafka()
            const halt = new AbortController()
            const { driving, journal } = startDrive(cardWith({ ratePerSecond: 10, driveFor: '1s' }), kafka.produce, {
                halt: halt.signal,
            })
            let summary: Summary | undefined
            void driving.then((ended) => (summary = ended))

            await jest.advanceTimersByTimeAsync(haltAtMs)
            halt.abort()
            kafka.acknowledge()
            await jest.advanceTimersByTimeAsync(0)

            expect({ summary, journaled: journal.length }).toMatchObject({
                summary: { targetUnits: 5, offeredUnits: 5 },
                journaled: 5,
            })
        }
    )

    it.each<[string, true | undefined, object]>([
        [
            'a card that stops on a break keeps every step to its planned window and counts the overdue units as due',
            true,
            {
                steps: [
                    { fromMs: 0, toMs: 1000, dueUnits: 4, offeredUnits: 1 },
                    { fromMs: 1000, toMs: 2000, dueUnits: 40, offeredUnits: 40 },
                ],
                lastOfferMs: 1975,
                overdueOfferedAtMs: [],
            },
        ],
        [
            'a card that does not stop on a break offers the overdue units late, as one schedule',
            undefined,
            {
                steps: [
                    { fromMs: 0, toMs: 1000, dueUnits: 4, offeredUnits: 4 },
                    { fromMs: 1000, toMs: 2000, dueUnits: 40, offeredUnits: 40 },
                ],
                lastOfferMs: 1975,
                overdueOfferedAtMs: [1350, 1350, 1350],
            },
        ],
    ])('after a stall across a step boundary, %s', async (_story, stopOnBreak, expected) => {
        const ramped = rampedCard(
            4,
            [
                { scale: 1, for: '1s' },
                { scale: 10, for: '1s' },
            ],
            '2s',
            stopOnBreak
        )
        const startedAt = Date.now()
        const { driving, journal } = startDrive(ramped, ACKNOWLEDGED)

        await jest.advanceTimersByTimeAsync(0)
        jest.setSystemTime(startedAt + 1100)
        await jest.advanceTimersByTimeAsync(2000)
        const { steps } = await driving

        expect({
            steps: steps.map(({ startedAt: from, endedAt: to, dueUnits, offeredUnits }) => ({
                fromMs: from - startedAt,
                toMs: to - startedAt,
                dueUnits,
                offeredUnits,
            })),
            lastOfferMs: Math.max(...journal.map(({ offeredAt }) => offeredAt)) - startedAt,
            overdueOfferedAtMs: journal
                .filter(({ step, offeredAt }) => step === 0 && offeredAt - startedAt >= 1000)
                .map(({ offeredAt }) => offeredAt - startedAt),
        }).toEqual(expected)
    })

    const MINUTE = 60_000
    const CPU_BAR = { name: 'writer_cpu_under', params: { percent: 70 } }

    const cpuReadAfter =
        (delayMs: number, percent: number): LiveRamp['writerCpu'] =>
        ({ startedAt }) =>
            new Promise((resolve) => setTimeout(() => resolve([{ at: startedAt, percent }]), delayMs))
    const BROKE_AT_1X = {
        end: 'broke',
        sustainedScale: null,
        broke: {
            scale: 1,
            offeredPerSecond: 1,
            by: 'writer_cpu_under',
            kind: 'bar',
            at: expect.any(String),
            part: 'db:cyclotron',
        },
        reason: 'writer_cpu_under broke at the 1x step',
    }

    it.each<[string, LiveRamp['writerCpu'], object]>([
        [
            'its writer CPU broke the bar at the 1x step, read during the 2x step',
            cpuReadAfter(30_000, 90),
            {
                offeredSteps: [0, 1],
                steps: [
                    { fromMs: 0, toMs: MINUTE, firstOfferMs: 0 },
                    { fromMs: MINUTE, toMs: 105_000, firstOfferMs: MINUTE },
                ],
                ramp: BROKE_AT_1X,
            },
        ],
        [
            'its writer CPU broke the bar at the 1x step, read only after the 2x step was due to end',
            cpuReadAfter(MINUTE, 90),
            {
                offeredSteps: [0, 1],
                steps: [
                    { fromMs: 0, toMs: MINUTE, firstOfferMs: 0 },
                    { fromMs: MINUTE, toMs: 135_000, firstOfferMs: MINUTE, waitedFor: 0 },
                ],
                ramp: BROKE_AT_1X,
            },
        ],
        [
            'its writer CPU held the bar at the 1x step, read only after the 2x step was due to end',
            cpuReadAfter(MINUTE, 40),
            {
                offeredSteps: [0, 1, 2],
                steps: [
                    { fromMs: 0, toMs: MINUTE, firstOfferMs: 0 },
                    { fromMs: MINUTE, toMs: 135_000, firstOfferMs: MINUTE, waitedFor: 0 },
                    { fromMs: 135_000, toMs: 195_000, firstOfferMs: 135_000 },
                ],
                ramp: { end: 'ceiling', sustainedScale: 5, reason: 'every step held up to the 5x ceiling' },
            },
        ],
        [
            'its writer CPU read failed at the 1x step',
            () => Promise.reject(new Error('CloudWatch is down')),
            {
                offeredSteps: [0, 1],
                steps: [
                    { fromMs: 0, toMs: MINUTE, firstOfferMs: 0 },
                    { fromMs: MINUTE, toMs: 75_000, firstOfferMs: MINUTE },
                ],
                ramp: {
                    end: 'harness_limit',
                    sustainedScale: null,
                    broke: {
                        scale: 1,
                        offeredPerSecond: 1,
                        by: 'run_host',
                        kind: 'harness',
                        at: expect.any(String),
                        part: null,
                    },
                    reason: 'writer_cpu_under was not judged: CloudWatch is down in the 1x step',
                },
            },
        ],
    ])(
        'a break at step N halts the drive by the end of step N+1, and step N+2 never starts before step N is judged, when %s',
        async (_story, writerCpu, expected) => {
            jest.setSystemTime(Math.ceil(Date.now() / MINUTE) * MINUTE)
            const ramped = rampedCard(
                1,
                [
                    { scale: 1, for: '1m' },
                    { scale: 2, for: '1m' },
                    { scale: 5, for: '1m' },
                ],
                '3m',
                true
            )
            const startedAt = Date.now()
            let journaled: JournalEntry[] = []
            const watch = watchRamp(
                {
                    minOffered: 0.9,
                    bars: [CPU_BAR],
                    gates: {},
                    judgesRefusals: false,
                    driveStartedAt: startedAt,
                    profile: {},
                    journal: () => journaled,
                    samples: () => [],
                    host: () => [],
                    queue: () => [],
                    writerCpu,
                },
                NEVER_ABORTED
            )
            const { driving, journal } = startDrive(ramped, ACKNOWLEDGED, { halt: watch.halt, gate: watch.gate })
            journaled = journal

            await jest.advanceTimersByTimeAsync(5 * MINUTE)
            const { steps } = await driving

            expect({
                offeredSteps: [...new Set(journal.map(({ step }) => step))],
                steps: steps.map(({ index, startedAt: from, endedAt: to, waitedFor }) => ({
                    fromMs: from - startedAt,
                    toMs: to - startedAt,
                    firstOfferMs:
                        Math.min(...journal.filter(({ step }) => step === index).map((unit) => unit.offeredAt)) -
                        startedAt,
                    ...(waitedFor !== undefined && { waitedFor }),
                })),
                ramp: rampOf({
                    planned: stepsOf(ramped.card.drive),
                    steps,
                    minOffered: 0.9,
                    stop: watch.stopped(),
                    bars: [],
                    invariants: [],
                    gates: {},
                    journal,
                    admissions: [],
                    converged: true,
                }),
            }).toEqual(expected)
        }
    )

    it('returns when its last step ends, without waiting for a step gate still pending', async () => {
        const gate: StepGate = () => new Promise<void>(() => undefined)
        const ramped = rampedCard(
            2,
            [
                { scale: 1, for: '1s' },
                { scale: 2, for: '1s' },
            ],
            '2s',
            true
        )
        const { driving } = startDrive(ramped, ACKNOWLEDGED, { gate })
        let summary: Summary | undefined
        void driving.then((ended) => (summary = ended))

        await jest.advanceTimersByTimeAsync(2000)

        expect(summary).toMatchObject({ targetUnits: 6, offeredUnits: 6 })
    })

    it('counts no acknowledgement for a step that stops on a break once that step ended, live or in the summary', async () => {
        const kafka = heldKafka()
        const offered: (() => number)[] = []
        const gate: StepGate = (_step, offeredSoFar) => {
            offered.push(offeredSoFar)
            return Promise.resolve()
        }
        const ramped = rampedCard(
            4,
            [
                { scale: 1, for: '1s' },
                { scale: 2, for: '1s' },
            ],
            '2s',
            true
        )
        const { driving } = startDrive(ramped, kafka.produce, { gate })

        await jest.advanceTimersByTimeAsync(1100)
        kafka.acknowledge()
        await jest.advanceTimersByTimeAsync(800)
        kafka.acknowledge()
        await jest.advanceTimersByTimeAsync(200)
        const { steps } = await driving

        expect({ live: offered.map((count) => count()), steps: steps.map(({ offeredUnits }) => offeredUnits) }).toEqual(
            {
                live: [0],
                steps: [0, 8],
            }
        )
    })

    it.each<[string, (startedAt: number) => Promise<void>, object, number?]>([
        [
            'the gate answered in its second extra cycle',
            () => jest.advanceTimersByTimeAsync(3500),
            { targetUnits: 37, offeredUnits: 37, held: { dueUnits: 21, offeredUnits: 21 }, burst: 1 },
        ],
        [
            'the event loop stalled across two extra cycles',
            async (startedAt) => {
                await jest.advanceTimersByTimeAsync(2100)
                jest.setSystemTime(startedAt + 4600)
                await jest.advanceTimersByTimeAsync(200)
            },
            { targetUnits: 47, offeredUnits: 32, held: { dueUnits: 31, offeredUnits: 16 }, burst: 6 },
        ],
        [
            'the gate answered as the event loop woke from a stall across two extra cycles',
            async (startedAt) => {
                await jest.advanceTimersByTimeAsync(2100)
                jest.setSystemTime(startedAt + 4600)
            },
            { targetUnits: 45, offeredUnits: 25, held: { dueUnits: 29, offeredUnits: 9 }, burst: 1 },
        ],
        [
            'the gate answered in the millisecond a unit went out after a stall',
            async (startedAt) => {
                await jest.advanceTimersByTimeAsync(2100)
                jest.setSystemTime(startedAt + 3124)
                await jest.advanceTimersByTimeAsync(126)
            },
            { targetUnits: 35, offeredUnits: 28, held: { dueUnits: 19, offeredUnits: 12 }, burst: 2 },
        ],
        [
            'the gate answered in the millisecond a unit was due after a stall, before it went out',
            async (startedAt) => {
                await jest.advanceTimersByTimeAsync(2100)
                jest.setSystemTime(startedAt + 3250)
            },
            { targetUnits: 34, offeredUnits: 25, held: { dueUnits: 18, offeredUnits: 9 }, burst: 1 },
        ],
        [
            'the gate answered in the millisecond a unit went out just before its slot after a stall',
            async (startedAt) => {
                await jest.advanceTimersByTimeAsync(2100)
                jest.setSystemTime(startedAt + 3050)
                await jest.advanceTimersByTimeAsync(137)
            },
            { targetUnits: 135, offeredUnits: 107, held: { dueUnits: 71, offeredUnits: 43 }, burst: 3 },
            16,
        ],
    ])(
        'while a step holds for the gate of the step before it, %s',
        async (_story, wait, expected, ratePerSecond = 4) => {
            let answer = (): void => undefined
            const gate: StepGate = ({ index }) =>
                index === 0 ? new Promise<void>((resolve) => (answer = resolve)) : Promise.resolve()
            const ramped = rampedCard(
                ratePerSecond,
                [
                    { scale: 1, for: '1s' },
                    { scale: 2, for: '1s' },
                    { scale: 3, for: '1s' },
                ],
                '3s',
                true
            )
            const startedAt = Date.now()
            const { driving, journal } = startDrive(ramped, ACKNOWLEDGED, { gate })

            await wait(startedAt)
            answer()
            await jest.advanceTimersByTimeAsync(2000)
            const { targetUnits, offeredUnits, steps } = await driving
            const heldOfferedAt = journal.filter(({ step }) => step === 1).map(({ offeredAt }) => offeredAt)

            expect({
                targetUnits,
                offeredUnits,
                held: { dueUnits: steps[1].dueUnits, offeredUnits: steps[1].offeredUnits },
                burst: Math.max(...heldOfferedAt.map((at) => heldOfferedAt.filter((other) => other === at).length)),
            }).toEqual(expected)
        }
    )

    it('keeps the window open until the drive duration ends, after its last unit was offered', async () => {
        const { driving } = startDrive(cardWith({ ratePerSecond: 1, driveFor: '2s' }), ACKNOWLEDGED)
        let summary: Summary | undefined
        void driving.then((ended) => (summary = ended))

        await jest.advanceTimersByTimeAsync(1999)
        const beforeTheEnd = summary
        await jest.advanceTimersByTimeAsync(1)

        expect({ beforeTheEnd, summary }).toMatchObject({
            beforeTheEnd: undefined,
            summary: { targetUnits: 2, offeredUnits: 2 },
        })
    })

    it.each<[string, LoadedCard, (halt: AbortController, startedAt: number) => void, object]>([
        [
            'its timer fired 1 ms early',
            cardWith({ ratePerSecond: 50, driveFor: '100ms' }),
            (_halt, startedAt) => jest.setSystemTime(startedAt + 89),
            { lasted: 100, due: 5, offered: 5, overlapping: 0 },
        ],
        [
            'the drive was halted',
            cardWith({ ratePerSecond: 50, driveFor: '100ms' }),
            (halt) => halt.abort(),
            { lasted: 90, due: 5, offered: 5, overlapping: 0 },
        ],
        [
            'its timer fired 1 ms early before the next step of a ramp',
            rampedCard(
                50,
                [
                    { scale: 1, for: '100ms' },
                    { scale: 2, for: '100ms' },
                ],
                '200ms'
            ),
            (_halt, startedAt) => jest.setSystemTime(startedAt + 89),
            { lasted: 100, due: 5, offered: 5, overlapping: 0 },
        ],
    ])('ends a step at its planned end unless the drive stopped it: %s', async (_story, loaded, act, expected) => {
        const halt = new AbortController()
        const startedAt = Date.now()
        const { driving, journal } = startDrive(loaded, ACKNOWLEDGED, { halt: halt.signal })

        await jest.advanceTimersByTimeAsync(90)
        act(halt, startedAt)
        await jest.advanceTimersByTimeAsync(250)

        const { steps } = await driving
        const [step] = steps
        expect({
            lasted: step.endedAt - step.startedAt,
            due: step.dueUnits,
            offered: step.offeredUnits,
            overlapping: journal.filter(({ step: index, offeredAt }) =>
                steps.some(
                    (other) => other.index !== index && offeredAt >= other.startedAt && offeredAt < other.endedAt
                )
            ).length,
        }).toEqual(expected)
    })

    it('ends at an interrupt between units without waiting for the next unit', async () => {
        const interrupt = new AbortController()
        const { driving, journal } = startDrive(cardWith({ ratePerSecond: 1, driveFor: '1m' }), ACKNOWLEDGED, {
            signal: interrupt.signal,
        })
        let summary: Summary | undefined
        void driving.then((ended) => (summary = ended))

        await jest.advanceTimersByTimeAsync(0)
        interrupt.abort()
        await jest.advanceTimersByTimeAsync(0)

        expect({ summary, journaled: journal.map(({ unitId }) => unitId) }).toMatchObject({
            summary: { targetUnits: 60, offeredUnits: 1 },
            journaled: ['run-a-1'],
        })
    })

    it.each([
        ['rejects a drive whose journal fails to record', '100ms', 'Promise.resolve()', 'journal full'],
        ['stops a long drive at the first unit its journal fails to record', '5m', 'Promise.resolve()', 'journal full'],
        [
            'ends a drive interrupted while its journal fails to record',
            '5m',
            '(interrupt.abort(), new Promise((resolve) => setTimeout(resolve, 50)))',
            'ended',
        ],
    ])(
        '%s instead of crashing a plain Node process',
        async (_name, driveFor, produce, stdout) => {
            const script = `
            const path = require('path')
            const { load } = require(${JSON.stringify(path.join(__dirname, '..', 'cards'))})
            const { drive } = require(${JSON.stringify(path.join(__dirname, 'generator'))})
            const smoke = load(${JSON.stringify(path.join(__dirname, '..', 'cards', 'smoke.yaml'))})
            const card = {
                ...smoke,
                card: { ...smoke.card, drive: { ...smoke.card.drive, for: '${driveFor}', traffic: [{ name: 'event_email', params: {} }] } },
                profile: { ...smoke.profile, traffic: { event_email: { ratePerSecond: 50 } } },
            }
            const journal = { record: () => { throw new Error('journal full') } }
            const interrupt = new AbortController()
            const { kafkaEmit } = require(${JSON.stringify(path.join(__dirname, 'traffic'))})
            const context = { emit: kafkaEmit({ produce: () => ${produce} }, 'scenario_events_test'), runId: 'run-a' }
            drive(card, { teamIds: [7], flowIds: { event_email: { 7: 'flow-7' } } }, journal, interrupt.signal, context).then(
                () => process.stdout.write('ended'),
                (error) => process.stdout.write(error.message)
            )
        `

            const outcome = await new Promise<{ code: number | string; stdout: string }>((resolve) =>
                execFile(
                    path.join(__dirname, '..', '..', '..', 'node_modules', '.bin', 'tsx'),
                    ['-e', script],
                    { timeout: 15_000 },
                    (error, stdout) => resolve({ code: error ? (error.code ?? String(error.signal)) : 0, stdout })
                )
            )

            expect(outcome).toEqual({ code: 0, stdout })
        },
        30_000
    )

    it('offers every unit that fell due during a stall in one turn', async () => {
        const startedAt = Date.now()
        const { driving, journal } = startDrive(cardWith({ ratePerSecond: 1000, driveFor: '1s' }), ACKNOWLEDGED)

        jest.setSystemTime(startedAt + 500)
        await jest.runOnlyPendingTimersAsync()

        expect(journal).toHaveLength(Date.now() - startedAt + 1)
        await jest.advanceTimersByTimeAsync(1000)
        expect(await driving).toMatchObject({ targetUnits: 1000, offeredUnits: 1000 })
    })

    it('picks the same teams for the same seed and other teams for another seed', async () => {
        const firstTeamsFor = async (seed: number): Promise<number[]> => {
            const card = cardWith({ seed, ratePerSecond: 100, driveFor: '100ms' })
            const { driving, journal } = startDrive(card, ACKNOWLEDGED, { teamIds: [1, 2, 3, 4] })
            await jest.advanceTimersByTimeAsync(100)
            await driving
            return journal.slice(0, 8).map(({ teamId }) => teamId)
        }

        const first = await firstTeamsFor(1)

        expect(first).toHaveLength(8)
        expect(await firstTeamsFor(1)).toEqual(first)
        expect(await firstTeamsFor(2)).not.toEqual(first)
    })

    it.each<[string, Partial<LoadedCard['card']['drive']>, Record<string, number>[]]>([
        [
            'a card without a ramp offers the base rates for the whole drive',
            { for: '2s' },
            [
                { email: 4, webhook: 2 },
                { email: 4, webhook: 2 },
            ],
        ],
        [
            'a ramped card multiplies every base rate by its step and keeps the split between kinds',
            {
                for: '2s',
                ramp: [
                    { scale: 1, for: '1s' },
                    { scale: 10, for: '1s' },
                ],
            },
            [
                { email: 4, webhook: 2 },
                { email: 40, webhook: 20 },
            ],
        ],
    ])('%s', async (_story, ramped, expected) => {
        const card: LoadedCard = {
            ...SMOKE,
            card: {
                ...SMOKE.card,
                drive: {
                    ...SMOKE.card.drive,
                    traffic: [
                        { name: 'event_email', params: {} },
                        { name: 'event_webhook', params: {} },
                    ],
                    ...ramped,
                },
            },
            profile: {
                ...SMOKE.profile,
                traffic: { event_email: { ratePerSecond: 4 }, event_webhook: { ratePerSecond: 2 } },
            },
        }
        const journal: JournalEntry[] = []
        const seeded = {
            teamIds: [7],
            flowIds: { event_email: { 7: 'email-flow' }, event_webhook: { 7: 'webhook-flow' } },
        }
        const startedAt = Date.now()
        const driving = drive(card, seeded, { record: (entry) => journal.push(entry) }, NEVER_ABORTED, {
            emit: kafkaEmit({ produce: ACKNOWLEDGED }, 'scenario_events_test'),
            cdpApi: CDP_API,
            sesFeedback: NO_FEEDBACK,
            runId: 'run-a',
        })

        await jest.advanceTimersByTimeAsync(2000)
        await driving

        const offeredIn = (fromMs: number): Record<string, number> => {
            const inStep = journal.filter(
                ({ offeredAt }) => offeredAt - startedAt >= fromMs && offeredAt - startedAt < fromMs + 1000
            )
            return Object.fromEntries(
                [
                    ...Map.groupBy(inStep, ({ expect }) => (expect.deliveries.includes('email') ? 'email' : 'webhook')),
                ].map(([kind, units]) => [kind, units.length])
            )
        }
        expect([offeredIn(0), offeredIn(1000)]).toEqual(expected)
    })
})
