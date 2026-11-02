import type { PostHog } from 'posthog-js'

import type { ConversationTicket } from '../../types'

const START = 1_000_000
const MAX_AGE_MS = 10_000
const OPTIONS = { maxAgeMs: MAX_AGE_MS }

const ticket = (id: string): ConversationTicket => ({ id }) as ConversationTicket

describe('loadTicketsAcrossTabs', () => {
    let now: number
    let posthog: PostHog
    let loadTicketsAcrossTabs: typeof import('./ticketsAcrossTabs').loadTicketsAcrossTabs
    let clearSharedTickets: typeof import('./ticketsAcrossTabs').clearSharedTickets
    let ticketsBackoffRemainingMs: typeof import('./ticketsAcrossTabs').ticketsBackoffRemainingMs
    let TicketsBackoffError: typeof import('./ticketsAcrossTabs').TicketsBackoffError

    const fetchingTickets = (...ids: string[]): jest.Mock => jest.fn().mockResolvedValue(ids.map(ticket))
    const rateLimited = (): jest.Mock =>
        jest.fn().mockRejectedValue(Object.assign(new Error('Too many requests'), { kind: 'rate_limit' }))

    beforeEach(async () => {
        now = START
        jest.spyOn(Date, 'now').mockImplementation(() => now)
        localStorage.clear()
        // A logout stops the module for the life of the page, so each test needs a fresh copy
        jest.resetModules()
        posthog = (await import('posthog-js')).default
        ;({ loadTicketsAcrossTabs, clearSharedTickets, ticketsBackoffRemainingMs, TicketsBackoffError } =
            await import('./ticketsAcrossTabs'))
    })

    afterEach(() => {
        jest.restoreAllMocks()
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

        clearSharedTickets()
        await loadTicketsAcrossTabs(fetchTickets, OPTIONS)

        expect(fetchTickets).toHaveBeenCalledTimes(2)
    })

    test.each([
        { name: 'in this tab', logOut: (): void => clearSharedTickets() },
        {
            name: 'in another tab',
            logOut: (): void => {
                localStorage.clear()
                window.dispatchEvent(new StorageEvent('storage', { key: 'posthog-conversations-tickets' }))
            },
        },
    ])('stops storing tickets after a logout $name', async ({ logOut }) => {
        const fetchTickets = fetchingTickets('fetched')
        let finishFetch = (): void => {}
        const inFlight = loadTicketsAcrossTabs(
            () => new Promise((resolve) => (finishFetch = () => resolve([ticket('in-flight')]))),
            OPTIONS
        )

        logOut()
        finishFetch()
        await inFlight
        await loadTicketsAcrossTabs(fetchTickets, OPTIONS)
        await loadTicketsAcrossTabs(fetchTickets, OPTIONS)

        expect(localStorage.length).toBe(0)
        expect(fetchTickets).toHaveBeenCalledTimes(2)
    })

    test.each([
        { name: 'returns the stored tickets', storedIds: ['stored'], expected: (): unknown => [ticket('stored')] },
        {
            name: 'throws without stored tickets',
            storedIds: [],
            expected: (): unknown => expect.any(TicketsBackoffError),
        },
    ])('after a 429, a load during the backoff $name and sends no request', async ({ storedIds, expected }) => {
        if (storedIds.length) {
            await loadTicketsAcrossTabs(fetchingTickets(...storedIds), OPTIONS)
        }
        now += MAX_AGE_MS
        await expect(loadTicketsAcrossTabs(rateLimited(), OPTIONS)).rejects.toMatchObject({ kind: 'rate_limit' })

        const fetchTickets = fetchingTickets('fetched')
        const outcome = await loadTicketsAcrossTabs(fetchTickets, { ...OPTIONS, force: true }).catch(
            (error: unknown) => error
        )
        expect(outcome).toEqual(expected())
        expect(fetchTickets).not.toHaveBeenCalled()

        now += ticketsBackoffRemainingMs()
        expect(await loadTicketsAcrossTabs(fetchTickets, OPTIONS)).toEqual([ticket('fetched')])
    })

    it('doubles the backoff for each 429 in a row up to the maximum', async () => {
        const delays: number[] = []
        for (let attempt = 0; attempt < 6; attempt++) {
            await expect(loadTicketsAcrossTabs(rateLimited(), OPTIONS)).rejects.toMatchObject({ kind: 'rate_limit' })
            delays.push(ticketsBackoffRemainingMs())
            now += ticketsBackoffRemainingMs()
        }

        expect(delays).toEqual([30_000, 60_000, 120_000, 240_000, 300_000, 300_000])
    })

    it('still fetches from the network when storage throws', async () => {
        const denied = (): never => {
            throw new DOMException('denied', 'SecurityError')
        }
        jest.spyOn(Storage.prototype, 'getItem').mockImplementation(denied)
        jest.spyOn(Storage.prototype, 'setItem').mockImplementation(denied)
        jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(denied)

        expect(await loadTicketsAcrossTabs(fetchingTickets('fetched'), OPTIONS)).toEqual([ticket('fetched')])
        expect(() => clearSharedTickets()).not.toThrow()
    })
})
