import posthog from 'posthog-js'

import type { ConversationTicket } from '../../types'

export interface TicketsSnapshot {
    tickets: ConversationTicket[]
    fetchedAt: number
}

export interface AcrossTabsDeps {
    now: () => number
    read: () => Promise<TicketsSnapshot | null>
    write: (snapshot: TicketsSnapshot) => Promise<boolean>
    announce: () => void
    withLock: <T>(fn: () => Promise<T>) => Promise<T>
}

const DB_NAME = 'posthog-conversations'
const STORE_NAME = 'shared'
const CHANNEL_NAME = 'posthog-conversations-tickets'
const LOCK_WAIT_MS = 15_000

/** The second freshness check inside the lock lets the tabs that queued behind it reuse its result. */
export async function loadTicketsAcrossTabs(
    fetchTickets: () => Promise<ConversationTicket[] | null>,
    options: { force?: boolean; maxAgeMs: number },
    deps: AcrossTabsDeps = browserDeps()
): Promise<ConversationTicket[] | null> {
    const readFresh = async (): Promise<ConversationTicket[] | null> => {
        if (options.force) {
            return null
        }
        const snapshot = await deps.read()
        return snapshot && deps.now() - snapshot.fetchedAt < options.maxAgeMs ? snapshot.tickets : null
    }

    return (
        (await readFresh()) ??
        deps.withLock(async () => {
            const fresh = await readFresh()
            if (fresh) {
                return fresh
            }
            const tickets = await fetchTickets()
            if (tickets && (await deps.write({ tickets, fetchedAt: deps.now() }))) {
                deps.announce()
            }
            return tickets
        })
    )
}

export function subscribeToSharedTickets(onChange: (tickets: ConversationTicket[]) => void): () => void {
    if (typeof BroadcastChannel === 'undefined') {
        return () => {}
    }
    const channel = new BroadcastChannel(CHANNEL_NAME)
    channel.onmessage = async () => {
        const snapshot = await browserDeps().read()
        if (snapshot) {
            onChange(snapshot.tickets)
        }
    }
    return () => channel.close()
}

export async function clearSharedTickets(): Promise<void> {
    await runRequest('readwrite', (store) => store.clear())
}

function browserDeps(): AcrossTabsDeps {
    // The widget fetches tickets as its signed identity, which can differ from the current distinct id
    // when another tab logs in as someone else, so that identity scopes the stored tickets.
    const currentKey = (): string => posthog.config?.identity_distinct_id ?? posthog.get_distinct_id?.() ?? ''
    const key = currentKey()
    return {
        now: () => Date.now(),
        read: async () => (await runRequest('readonly', (store) => store.get(key))) as TicketsSnapshot | null,
        write: async (snapshot) => {
            if (currentKey() !== key) {
                return false
            }
            // Only the latest snapshot stays, so a person who used this browser earlier leaves nothing behind.
            const written = await runRequest('readwrite', (store) => {
                store.clear()
                return store.put(snapshot, key)
            })
            return written !== null
        },
        announce: () => {
            if (typeof BroadcastChannel !== 'undefined') {
                const channel = new BroadcastChannel(CHANNEL_NAME)
                channel.postMessage(null)
                channel.close()
            }
        },
        withLock: (fn) => withBrowserLock(`posthog-conversations-tickets:${key}`, fn),
    }
}

async function withBrowserLock<T>(name: string, fn: () => Promise<T>): Promise<T> {
    if (typeof navigator === 'undefined' || !navigator.locks) {
        return fn()
    }
    let started = false
    try {
        return await navigator.locks.request(name, { signal: AbortSignal.timeout(LOCK_WAIT_MS) }, () => {
            started = true
            return fn()
        })
    } catch (e) {
        // A tab that holds the lock for too long must not block the others for good.
        if (!started && e instanceof DOMException && (e.name === 'AbortError' || e.name === 'TimeoutError')) {
            return fn()
        }
        throw e
    }
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
