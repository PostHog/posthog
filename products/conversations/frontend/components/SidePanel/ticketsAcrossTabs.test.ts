import posthog from 'posthog-js'

import type { ConversationTicket } from '../../types'
import { clearSharedTickets, loadTicketsAcrossTabs } from './ticketsAcrossTabs'

const START = 1_000_000
const MAX_AGE_MS = 10_000
const OPTIONS = { maxAgeMs: MAX_AGE_MS }

const ticket = (id: string): ConversationTicket => ({ id }) as ConversationTicket

describe('loadTicketsAcrossTabs', () => {
    const originalIndexedDB = globalThis.indexedDB
    let now: number

    const fetchingTickets = (...ids: string[]): jest.Mock => jest.fn().mockResolvedValue(ids.map(ticket))

    beforeEach(async () => {
        now = START
        jest.spyOn(Date, 'now').mockImplementation(() => now)
        await new Promise((resolve) => {
            const request = indexedDB.deleteDatabase('posthog-conversations')
            request.onsuccess = request.onerror = () => resolve(null)
        })
    })

    afterEach(() => {
        jest.restoreAllMocks()
        globalThis.indexedDB = originalIndexedDB
        ;(posthog as any).config = undefined
    })

    test.each([
        { name: 'under the max age', ageMs: MAX_AGE_MS - 1, force: false, fetches: 1 },
        { name: 'at the max age', ageMs: MAX_AGE_MS, force: false, fetches: 2 },
        { name: 'under the max age but forced', ageMs: 1, force: true, fetches: 2 },
    ])('fetches $fetches time(s) for a second load $name', async ({ ageMs, force, fetches }) => {
        const fetchTickets = fetchingTickets('fetched')

        await loadTicketsAcrossTabs(fetchTickets, OPTIONS)
        now += ageMs
        const tickets = await loadTicketsAcrossTabs(fetchTickets, { ...OPTIONS, force })

        expect(fetchTickets).toHaveBeenCalledTimes(fetches)
        expect(tickets).toEqual([ticket('fetched')])
    })

    it('keeps the stored tickets when a fetch returns nothing', async () => {
        await loadTicketsAcrossTabs(fetchingTickets('stored'), OPTIONS)
        now += 1

        expect(await loadTicketsAcrossTabs(jest.fn().mockResolvedValue(null), { ...OPTIONS, force: true })).toBeNull()

        const fetchTickets = fetchingTickets('fetched')
        expect(await loadTicketsAcrossTabs(fetchTickets, OPTIONS)).toEqual([ticket('stored')])
        expect(fetchTickets).not.toHaveBeenCalled()
    })

    it('never reuses tickets fetched for another identity', async () => {
        const fetchTickets = fetchingTickets('a-ticket')
        ;(posthog as any).config = { identity_distinct_id: 'person-a' }
        await loadTicketsAcrossTabs(fetchTickets, OPTIONS)
        ;(posthog as any).config = { identity_distinct_id: 'person-b' }

        await loadTicketsAcrossTabs(fetchTickets, OPTIONS)

        expect(fetchTickets).toHaveBeenCalledTimes(2)
    })

    it('fetches again after the stored tickets are cleared', async () => {
        const fetchTickets = fetchingTickets('fetched')
        await loadTicketsAcrossTabs(fetchTickets, OPTIONS)

        await clearSharedTickets()
        await loadTicketsAcrossTabs(fetchTickets, OPTIONS)

        expect(fetchTickets).toHaveBeenCalledTimes(2)
    })

    it('still fetches from the network when IndexedDB throws on open', async () => {
        globalThis.indexedDB = {
            open: () => {
                throw new DOMException('denied', 'SecurityError')
            },
        } as unknown as IDBFactory

        expect(await loadTicketsAcrossTabs(fetchingTickets('fetched'), OPTIONS)).toEqual([ticket('fetched')])
    })
})
