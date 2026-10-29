import posthog from 'posthog-js'

import type { ConversationTicket } from '../../types'

interface TicketsSnapshot {
    tickets: ConversationTicket[]
    fetchedAt: number
}

const DB_NAME = 'posthog-conversations'
const STORE_NAME = 'shared'

export async function loadTicketsAcrossTabs(
    fetchTickets: () => Promise<ConversationTicket[] | null>,
    options: { force?: boolean; maxAgeMs: number }
): Promise<ConversationTicket[] | null> {
    // The widget fetches tickets as its signed identity, which can differ from the current distinct id
    // when another tab logs in as someone else, so that identity scopes the stored tickets.
    const key = posthog.config?.identity_distinct_id ?? posthog.get_distinct_id?.() ?? ''

    if (!options.force) {
        const snapshot = (await runRequest('readonly', (store) => store.get(key))) as TicketsSnapshot | null
        if (snapshot && Date.now() - snapshot.fetchedAt < options.maxAgeMs) {
            return snapshot.tickets
        }
    }

    const tickets = await fetchTickets()
    if (tickets) {
        // Only the latest snapshot stays, so a person who used this browser earlier leaves nothing behind.
        await runRequest('readwrite', (store) => {
            store.clear()
            return store.put({ tickets, fetchedAt: Date.now() }, key)
        })
    }
    return tickets
}

export async function clearSharedTickets(): Promise<void> {
    await runRequest('readwrite', (store) => store.clear())
}

function openDb(): Promise<IDBDatabase | null> {
    if (typeof indexedDB === 'undefined') {
        return Promise.resolve(null)
    }
    return new Promise((resolve) => {
        try {
            const request = indexedDB.open(DB_NAME, 1)
            request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME)
            request.onsuccess = () => resolve(request.result)
            request.onerror = () => resolve(null)
        } catch {
            resolve(null)
        }
    })
}

// IndexedDB can be missing or blocked, for example in private windows. The tickets then come from the network only.
async function runRequest(
    mode: IDBTransactionMode,
    makeRequest: (store: IDBObjectStore) => IDBRequest
): Promise<unknown> {
    const db = await openDb()
    if (!db) {
        return null
    }
    return new Promise((resolve) => {
        try {
            const request = makeRequest(db.transaction(STORE_NAME, mode).objectStore(STORE_NAME))
            request.onsuccess = () => resolve(request.result ?? null)
            request.onerror = () => resolve(null)
        } catch {
            resolve(null)
        }
    }).finally(() => db.close())
}
