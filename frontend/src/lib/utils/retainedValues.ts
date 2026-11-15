import { getContext } from 'kea'

import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'

export type RetainedValuesOptions<T> = {
    maxEntries: number
    ttlMs: number
    /** Budget for all entries together, in the units `sizeOf` returns. */
    maxTotalSize?: number
    maxEntrySize?: number
    sizeOf?: (value: T) => number
    /** Prefix ids with the current project. Off when ids already name the project. */
    scopeToProject?: boolean
}

/** A timer for cleanup work that must not keep a Node process alive, such as a test worker. */
export function setBackgroundTimeout(callback: () => void, ms: number): ReturnType<typeof setTimeout> {
    const timer = setTimeout(callback, ms)
    ;(timer as { unref?: () => void }).unref?.()
    return timer
}

type Entry<T> = { value: T; expiresAt: number; size: number }
type Store<T> = { entries: Map<string, Entry<T>>; totalSize: number; sweepTimer: ReturnType<typeof setTimeout> | null }

/**
 * A bounded cache of recently loaded values with least recently used eviction. Expired values are
 * swept on a timer, so memory comes back after the TTL even when nothing reads the cache again.
 * Each kea context gets its own store, which isolates tests from each other.
 */
export class RetainedValues<T> {
    private readonly stores = new WeakMap<ReturnType<typeof getContext>, Store<T>>()

    constructor(private readonly options: RetainedValuesOptions<T>) {}

    get(id: string): T | null {
        const key = this.key(id)
        if (!key) {
            return null
        }
        const store = this.store()
        const entry = store.entries.get(key)
        if (!entry || entry.expiresAt <= Date.now()) {
            this.deleteEntry(store, key)
            return null
        }
        store.entries.delete(key)
        store.entries.set(key, entry)
        return entry.value
    }

    set(id: string, value: T, size?: number): void {
        this.setIn(this.store(), id, value, size)
    }

    /** A setter bound to the current kea context, for a value that may arrive after the context changed. */
    bindSet(): (id: string, value: T, size?: number) => void {
        const store = this.store()
        return (id, value, size) => this.setIn(store, id, value, size)
    }

    delete(id: string): void {
        const key = this.key(id)
        if (key) {
            this.deleteEntry(this.store(), key)
        }
    }

    private setIn(store: Store<T>, id: string, value: T, knownSize?: number): void {
        const key = this.key(id)
        if (!key) {
            return
        }
        const { maxEntries, maxTotalSize = Infinity, maxEntrySize = Infinity, ttlMs, sizeOf } = this.options
        const size = knownSize ?? sizeOf?.(value) ?? 0
        this.deleteEntry(store, key)
        if (size > maxEntrySize) {
            return
        }
        store.entries.set(key, { value, expiresAt: Date.now() + ttlMs, size })
        store.totalSize += size
        while (store.entries.size > maxEntries || store.totalSize > maxTotalSize) {
            this.deleteEntry(store, store.entries.keys().next().value!)
        }
        this.scheduleSweep(store)
    }

    // The TTL is the same for every entry, so the timer only has to wake for the next expiry.
    // `after` makes each wake-up move forward, so a test that pins the clock can't reschedule forever.
    private scheduleSweep(store: Store<T>, after: number = -Infinity): void {
        if (store.sweepTimer) {
            return
        }
        let nextExpiry = Infinity
        for (const entry of store.entries.values()) {
            nextExpiry = Math.min(nextExpiry, entry.expiresAt)
        }
        if (nextExpiry === Infinity || nextExpiry <= after) {
            return
        }
        store.sweepTimer = setBackgroundTimeout(
            () => {
                store.sweepTimer = null
                const now = Date.now()
                for (const [key, entry] of store.entries) {
                    if (entry.expiresAt <= now) {
                        this.deleteEntry(store, key)
                    }
                }
                this.scheduleSweep(store, nextExpiry)
            },
            Math.max(nextExpiry - Date.now(), 1000)
        )
    }

    private deleteEntry(store: Store<T>, key: string): void {
        const entry = store.entries.get(key)
        if (entry) {
            store.totalSize -= entry.size
            store.entries.delete(key)
        }
    }

    // Ids such as insight and notebook short ids are unique only within a project.
    private key(id: string): string | null {
        if (this.options.scopeToProject === false) {
            return id
        }
        const teamId = getCurrentTeamIdOrNone()
        return teamId ? `${teamId}:${id}` : null
    }

    private store(): Store<T> {
        const context = getContext()
        let store = this.stores.get(context)
        if (!store) {
            store = { entries: new Map(), totalSize: 0, sweepTimer: null }
            this.stores.set(context, store)
        }
        return store
    }
}
