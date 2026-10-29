import { IDBFactory } from 'fake-indexeddb'

import type { ConversationTicket } from '../../types'
import {
    clearSharedTickets,
    loadTicketsAcrossTabs,
    type AcrossTabsDeps,
    type TicketsSnapshot,
} from './ticketsAcrossTabs'

const NOW = 1_000_000
const MAX_AGE_MS = 10_000

const ticket = (id: string): ConversationTicket => ({ id }) as ConversationTicket

describe('loadTicketsAcrossTabs', () => {
    let stored: TicketsSnapshot | null
    let deps: AcrossTabsDeps
    let announce: jest.Mock

    beforeEach(() => {
        stored = null
        announce = jest.fn()
        deps = {
            now: () => NOW,
            read: async () => stored,
            write: async (snapshot) => {
                stored = snapshot
            },
            announce,
            withLock: (fn) => fn(),
        }
    })

    test.each([
        { name: 'empty store', snapshot: null, force: false, fetches: 1 },
        { name: 'stale snapshot', snapshot: { fetchedAt: NOW - MAX_AGE_MS }, force: false, fetches: 1 },
        { name: 'fresh snapshot', snapshot: { fetchedAt: NOW - MAX_AGE_MS + 1 }, force: false, fetches: 0 },
        { name: 'fresh snapshot but forced', snapshot: { fetchedAt: NOW - 1 }, force: true, fetches: 1 },
    ])('$name fetches $fetches time(s)', async ({ snapshot, force, fetches }) => {
        stored = snapshot && { tickets: [ticket('stored')], ...snapshot }
        const fetchTickets = jest.fn().mockResolvedValue([ticket('fetched')])

        const tickets = await loadTicketsAcrossTabs(fetchTickets, { force, maxAgeMs: MAX_AGE_MS }, deps)

        expect(fetchTickets).toHaveBeenCalledTimes(fetches)
        expect(tickets).toEqual([ticket(fetches ? 'fetched' : 'stored')])
        expect(announce).toHaveBeenCalledTimes(fetches)
    })

    it('shares one fetch between tabs that queue on the lock together', async () => {
        let queue: Promise<unknown> = Promise.resolve()
        deps.withLock = (fn) => {
            const run = queue.then(fn)
            queue = run.catch(() => undefined)
            return run
        }
        const fetchTickets = jest.fn().mockResolvedValue([ticket('fetched')])

        const results = await Promise.all(
            [1, 2, 3].map(() => loadTicketsAcrossTabs(fetchTickets, { maxAgeMs: MAX_AGE_MS }, deps))
        )

        expect(fetchTickets).toHaveBeenCalledTimes(1)
        expect(results).toEqual([[ticket('fetched')], [ticket('fetched')], [ticket('fetched')]])
    })

    it('keeps the stored snapshot when the fetch returns nothing', async () => {
        stored = { tickets: [ticket('stored')], fetchedAt: NOW - MAX_AGE_MS }
        const fetchTickets = jest.fn().mockResolvedValue(null)

        const tickets = await loadTicketsAcrossTabs(fetchTickets, { maxAgeMs: MAX_AGE_MS }, deps)

        expect(tickets).toBeNull()
        expect(stored?.tickets).toEqual([ticket('stored')])
        expect(announce).not.toHaveBeenCalled()
    })

    describe('with the browser storage', () => {
        beforeEach(() => {
            globalThis.indexedDB = new IDBFactory()
        })

        afterEach(() => {
            Object.defineProperty(navigator, 'locks', { value: undefined, configurable: true })
        })

        test.each([
            {
                name: 'the lock wait times out',
                breakStorage: () =>
                    Object.defineProperty(navigator, 'locks', {
                        value: { request: jest.fn().mockRejectedValue(new DOMException('timeout', 'TimeoutError')) },
                        configurable: true,
                    }),
            },
            {
                name: 'IndexedDB throws on open',
                breakStorage: () => {
                    globalThis.indexedDB = {
                        open: () => {
                            throw new DOMException('denied', 'SecurityError')
                        },
                    } as unknown as IDBFactory
                },
            },
        ])('still fetches from the network when $name', async ({ breakStorage }) => {
            breakStorage()
            const fetchTickets = jest.fn().mockResolvedValue([ticket('fetched')])

            const tickets = await loadTicketsAcrossTabs(fetchTickets, { maxAgeMs: MAX_AGE_MS })

            expect(tickets).toEqual([ticket('fetched')])
        })

        it('leaves no stored tickets behind after they are cleared', async () => {
            const fetchTickets = jest.fn().mockResolvedValue([ticket('fetched')])

            await loadTicketsAcrossTabs(fetchTickets, { maxAgeMs: MAX_AGE_MS })
            await loadTicketsAcrossTabs(fetchTickets, { maxAgeMs: MAX_AGE_MS })
            expect(fetchTickets).toHaveBeenCalledTimes(1)

            await clearSharedTickets()
            await loadTicketsAcrossTabs(fetchTickets, { maxAgeMs: MAX_AGE_MS })
            expect(fetchTickets).toHaveBeenCalledTimes(2)
        })
    })
})
