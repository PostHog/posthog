import { execFile } from 'child_process'
import path from 'path'

import { LoadedCard, load } from '../cards'
import type { JournalEntry } from '../judge/judge'
import { SeedState, drive } from './generator'
import type { OfferContext } from './traffic'

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

type Produce = OfferContext['producer']['produce']
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

function startDrive(
    loaded: LoadedCard,
    produce: Produce,
    {
        teamIds = [7],
        signal = NEVER_ABORTED,
        sesFeedback = NO_FEEDBACK,
    }: { teamIds?: number[]; signal?: AbortSignal; sesFeedback?: OfferContext['sesFeedback'] } = {}
): { driving: Promise<Summary>; journal: JournalEntry[] } {
    const journal: JournalEntry[] = []
    const seeded = seededFor(teamIds, loaded.card.drive.traffic[0].name)
    const driving = drive(loaded, seeded, { record: (entry) => journal.push(entry) }, signal, {
        producer: { produce },
        eventsTopic: 'scenario_events_test',
        cdpApi: CDP_API,
        sesFeedback,
        runId: 'run-a',
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

    it.each<[string, number, (kafka: ReturnType<typeof heldKafka>) => void, Summary]>([
        ['every produce acknowledged', 100, (kafka) => kafka.acknowledge(), { targetUnits: 5, offeredUnits: 5 }],
        ['every produce rejected', 100, (kafka) => kafka.reject(), { targetUnits: 5, offeredUnits: 0 }],
        [
            'every produce acknowledged after the window',
            101,
            (kafka) => kafka.acknowledge(),
            { targetUnits: 5, offeredUnits: 0 },
        ],
    ])(
        'counts a unit as offered once Kafka acknowledged it inside the window: %s',
        async (_story, answeredAtMs, answer, expected) => {
            const kafka = heldKafka()
            const { driving } = startDrive(cardWith({ ratePerSecond: 50, driveFor: '100ms' }), kafka.produce)

            await jest.advanceTimersByTimeAsync(answeredAtMs)
            answer(kafka)

            expect(await driving).toEqual(expected)
        }
    )

    it.each<[string, Produce, object]>([
        [
            'its first send was accepted',
            () => Promise.resolve(),
            {
                followUps: ['run-a-1'],
                journal: [{ unitId: 'run-a-1', answer: { accepted: true }, followUp: { notSent: 'no feedback' } }],
                summary: { targetUnits: 1, offeredUnits: 1 },
            },
        ],
        [
            'its first send was refused',
            () => Promise.reject(new Error('broker down')),
            {
                followUps: [],
                journal: [{ unitId: 'run-a-1', answer: { accepted: false }, followUp: undefined }],
                summary: { targetUnits: 1, offeredUnits: 0 },
            },
        ],
    ])(
        'journals a follow-up after the window with the unit, and counts it by its first answer, once %s',
        async (_story, produce, expected) => {
            const followUps: string[] = []
            const sesFeedback = {
                settled: (unitId: string) => {
                    followUps.push(unitId)
                    return new Promise<string>((resolve) => setTimeout(() => resolve('no feedback'), 5000))
                },
            }
            const { driving, journal } = startDrive(
                cardWith({ ratePerSecond: 10, driveFor: '100ms', traffic: 'bounce_followup' }),
                produce,
                { sesFeedback }
            )

            await jest.advanceTimersByTimeAsync(5000)

            expect({
                summary: await driving,
                followUps,
                journal: journal.map(({ unitId, answer, followUp }) => ({ unitId, answer, followUp })),
            }).toMatchObject(expected)
        }
    )

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

        expect({ summary, journaled: journal.map(({ unitId }) => unitId) }).toEqual({
            summary: { targetUnits: 5, offeredUnits: 2 },
            journaled: ['run-a-1', 'run-a-2'],
        })
    })

    it('keeps the window open until the drive duration ends, after its last unit was offered', async () => {
        const { driving } = startDrive(cardWith({ ratePerSecond: 1, driveFor: '2s' }), ACKNOWLEDGED)
        let summary: Summary | undefined
        void driving.then((ended) => (summary = ended))

        await jest.advanceTimersByTimeAsync(1999)
        const beforeTheEnd = summary
        await jest.advanceTimersByTimeAsync(1)

        expect({ beforeTheEnd, summary }).toEqual({
            beforeTheEnd: undefined,
            summary: { targetUnits: 2, offeredUnits: 2 },
        })
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

        expect({ summary, journaled: journal.map(({ unitId }) => unitId) }).toEqual({
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
            const context = { producer: { produce: () => ${produce} }, eventsTopic: 'scenario_events_test', runId: 'run-a' }
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
        expect(await driving).toEqual({ targetUnits: 1000, offeredUnits: 1000 })
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
})
