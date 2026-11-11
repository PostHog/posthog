import { getEventListeners } from 'events'
import path from 'path'

import { LoadedCard, load } from '../cards'
import type { JournalEntry } from '../judge/judge'
import { drive } from './generator'
import type { OfferContext } from './traffic'

const SMOKE = load(path.join(__dirname, '..', 'cards', 'smoke.yaml'))
const NEVER_ABORTED = new AbortController().signal

type Produce = OfferContext['producer']['produce']
type Summary = Awaited<ReturnType<typeof drive>>

function cardWith({ seed = 1, ratePerSecond, driveFor }: { seed?: number; ratePerSecond: number; driveFor: string }) {
    return {
        ...SMOKE,
        card: { ...SMOKE.card, seed, drive: { ...SMOKE.card.drive, for: driveFor } },
        profile: { ...SMOKE.profile, traffic: { event_email: { ratePerSecond } } },
    } satisfies LoadedCard
}

function startDrive(
    loaded: LoadedCard,
    produce: Produce,
    { teamIds = [7], signal = NEVER_ABORTED }: { teamIds?: number[]; signal?: AbortSignal } = {}
): { driving: Promise<Summary>; journal: JournalEntry[] } {
    const journal: JournalEntry[] = []
    const driving = drive(loaded, { teamIds }, { record: (entry) => journal.push(entry) }, signal, {
        producer: { produce },
        eventsTopic: 'scenario_events_test',
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

    it('stops waiting for acknowledgements on an interrupt and counts the pending units as not offered', async () => {
        const kafka = heldKafka()
        const interrupt = new AbortController()
        const { driving } = startDrive(cardWith({ ratePerSecond: 50, driveFor: '100ms' }), kafka.produce, {
            signal: interrupt.signal,
        })

        await jest.advanceTimersByTimeAsync(100)
        kafka.acknowledge(2)
        await jest.advanceTimersByTimeAsync(0)
        interrupt.abort()

        expect(await driving).toEqual({ targetUnits: 5, offeredUnits: 2 })
    })

    it('leaves no abort listener on the interrupt signal once a drive ends', async () => {
        const interrupt = new AbortController()
        const { driving } = startDrive(cardWith({ ratePerSecond: 50, driveFor: '100ms' }), ACKNOWLEDGED, {
            signal: interrupt.signal,
        })

        await jest.advanceTimersByTimeAsync(100)
        await driving

        expect(getEventListeners(interrupt.signal, 'abort')).toEqual([])
    })

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
