import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { LoadedCard, load } from '../cards'
import type { JournalEntry } from '../judge/judge'
import { drive } from './generator'
import type { OfferContext } from './traffic'

const SMOKE = load(path.join(__dirname, '..', 'cards', 'smoke.yaml'))
const NEVER_ABORTED = new AbortController().signal

function cardWith({ seed = 1, ratePerSecond, driveFor }: { seed?: number; ratePerSecond: number; driveFor: string }) {
    return {
        ...SMOKE,
        card: { ...SMOKE.card, seed, drive: { ...SMOKE.card.drive, for: driveFor } },
        profile: { ...SMOKE.profile, traffic: { event_email: { ratePerSecond } } },
    } satisfies LoadedCard
}

async function driveWith(
    loaded: LoadedCard,
    produce: OfferContext['producer']['produce'],
    teamIds = [7]
): Promise<{ summary: Awaited<ReturnType<typeof drive>>; journal: JournalEntry[] }> {
    const journal: JournalEntry[] = []
    const summary = await drive(loaded, { teamIds }, { record: (entry) => journal.push(entry) }, NEVER_ABORTED, {
        producer: { produce },
        eventsTopic: 'scenario_events_test',
        runId: 'run-a',
    })
    return { summary, journal }
}

describe('drive', () => {
    type Summary = Awaited<ReturnType<typeof drive>>
    const ACKNOWLEDGED: OfferContext['producer']['produce'] = () => Promise.resolve()

    it.each<[string, { ratePerSecond: number; driveFor: string }, OfferContext['producer']['produce'], Summary]>([
        [
            'every produce acknowledged',
            { ratePerSecond: 50, driveFor: '100ms' },
            ACKNOWLEDGED,
            { targetUnits: 5, offeredUnits: 5 },
        ],
        [
            'every produce rejected',
            { ratePerSecond: 50, driveFor: '100ms' },
            () => Promise.reject(new Error('broker down')),
            { targetUnits: 5, offeredUnits: 0 },
        ],
        [
            'every produce acknowledged after the window',
            { ratePerSecond: 50, driveFor: '100ms' },
            () => sleep(300).then(() => undefined),
            { targetUnits: 5, offeredUnits: 0 },
        ],
    ])(
        'counts a unit as offered once Kafka acknowledged it inside the window: %s',
        async (_story, card, produce, expected) => {
            const { summary } = await driveWith(cardWith(card), produce)

            expect(summary).toEqual(expected)
        }
    )

    it('keeps up with a rate of many units per millisecond', async () => {
        const { summary } = await driveWith(cardWith({ ratePerSecond: 10_000, driveFor: '300ms' }), ACKNOWLEDGED)

        expect(summary.targetUnits).toBe(3000)
        expect(summary.offeredUnits).toBeGreaterThanOrEqual(0.9 * summary.targetUnits)
    })

    it('picks the same teams for the same seed and other teams for another seed', async () => {
        const firstTeamsFor = async (seed: number): Promise<number[]> => {
            const card = cardWith({ seed, ratePerSecond: 100, driveFor: '100ms' })
            const { journal } = await driveWith(card, ACKNOWLEDGED, [1, 2, 3, 4])
            return journal.slice(0, 8).map(({ teamId }) => teamId)
        }

        const first = await firstTeamsFor(1)

        expect(first).toHaveLength(8)
        expect(await firstTeamsFor(1)).toEqual(first)
        expect(await firstTeamsFor(2)).not.toEqual(first)
    })
})
