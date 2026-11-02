import posthog from 'posthog-js'
import { z } from 'zod'

import { localStorageSlot } from 'lib/utils/localStorageSlot'

import type { ConversationTicket } from '../../types'

const STORAGE_KEY = 'posthog-conversations-tickets'

// One slot for every identity, so a person who used this browser earlier leaves nothing behind.
const sharedTickets = localStorageSlot(
    STORAGE_KEY,
    z.object({
        identity: z.string(),
        fetchedAt: z.number(),
        tickets: z.array(z.custom<ConversationTicket>()),
    })
)

const BACKOFF_STORAGE_KEY = 'posthog-conversations-tickets-backoff'
const MIN_BACKOFF_MS = 30 * 1000
const MAX_BACKOFF_MS = 5 * 60 * 1000

// Every signed-in person sends the same widget token, so the server puts all of them in one rate limit bucket.
// A rate limit therefore stops every tab in this browser, not only the tab that got the 429.
const ticketsBackoff = localStorageSlot(BACKOFF_STORAGE_KEY, z.object({ until: z.number(), delayMs: z.number() }))

export class TicketsBackoffError extends Error {
    constructor() {
        super('Tickets are rate limited. Try again later.')
        this.name = 'TicketsBackoffError'
    }
}

const isRateLimitError = (error: unknown): boolean =>
    !!error && typeof error === 'object' && (error as { kind?: unknown }).kind === 'rate_limit'

export function ticketsBackoffRemainingMs(): number {
    const backoff = ticketsBackoff.get()
    return backoff ? Math.max(0, backoff.until - Date.now()) : 0
}

// This page still fetches as the old identity after a logout, so it must not store that person's tickets again.
let loggedOut = false
window.addEventListener('storage', (event) => {
    if (event.key === STORAGE_KEY && event.newValue === null) {
        loggedOut = true
    }
})

export async function loadTicketsAcrossTabs(
    fetchTickets: () => Promise<ConversationTicket[] | null>,
    options: { force?: boolean; maxAgeMs: number }
): Promise<ConversationTicket[] | null> {
    // The widget fetches tickets as its signed identity, which can differ from the current distinct id
    // when another tab logs in as someone else, so that identity scopes the stored tickets.
    const identity = posthog.config?.identity_distinct_id ?? posthog.get_distinct_id?.() ?? ''

    const stored = sharedTickets.get()
    const storedForIdentity = stored?.identity === identity ? stored : null
    if (!options.force && storedForIdentity && Date.now() - storedForIdentity.fetchedAt < options.maxAgeMs) {
        return storedForIdentity.tickets
    }

    // A request during the backoff gets a 429 and makes the shared bucket recover more slowly.
    // Old tickets are better than an empty list, so return them when they exist.
    const backoff = ticketsBackoff.get()
    if (backoff && Date.now() < backoff.until) {
        if (storedForIdentity) {
            return storedForIdentity.tickets
        }
        throw new TicketsBackoffError()
    }

    let tickets: ConversationTicket[] | null
    try {
        tickets = await fetchTickets()
    } catch (error) {
        if (isRateLimitError(error)) {
            // Start again from the minimum when the last backoff ended long ago, so that one old 429 does not
            // make the next wait the maximum.
            const recentDelayMs = backoff && Date.now() - backoff.until < MAX_BACKOFF_MS ? backoff.delayMs : 0
            const delayMs = Math.min(MAX_BACKOFF_MS, Math.max(MIN_BACKOFF_MS, recentDelayMs * 2))
            ticketsBackoff.set({ until: Date.now() + delayMs, delayMs })
        }
        throw error
    }
    if (tickets && !loggedOut) {
        sharedTickets.set({ identity, fetchedAt: Date.now(), tickets })
    }
    return tickets
}

export function clearSharedTickets(): void {
    loggedOut = true
    try {
        localStorage.removeItem(STORAGE_KEY)
    } catch {
        // Disabled storage must not prevent logout.
    }
}
