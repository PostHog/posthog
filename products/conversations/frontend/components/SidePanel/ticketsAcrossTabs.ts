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

export async function loadTicketsAcrossTabs(
    fetchTickets: () => Promise<ConversationTicket[] | null>,
    options: { force?: boolean; maxAgeMs: number }
): Promise<ConversationTicket[] | null> {
    // The widget fetches tickets as its signed identity, which can differ from the current distinct id
    // when another tab logs in as someone else, so that identity scopes the stored tickets.
    const identity = posthog.config?.identity_distinct_id ?? posthog.get_distinct_id?.() ?? ''

    const stored = options.force ? null : sharedTickets.get()
    if (stored?.identity === identity && Date.now() - stored.fetchedAt < options.maxAgeMs) {
        return stored.tickets
    }

    const tickets = await fetchTickets()
    if (tickets) {
        sharedTickets.set({ identity, fetchedAt: Date.now(), tickets })
    }
    return tickets
}

export function clearSharedTickets(): void {
    try {
        localStorage.removeItem(STORAGE_KEY)
    } catch {
        // Disabled storage must not prevent logout.
    }
}
