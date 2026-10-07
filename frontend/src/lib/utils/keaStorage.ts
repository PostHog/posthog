import posthog from 'posthog-js'

// pinned: localStorage key. Renaming it resets every user's last-used times, so no key expires for a full TTL.
export const LAST_USED_STORAGE_KEY = 'posthog.kea-storage.last-used'
export const KEA_STORAGE_TTL_MS = 30 * 24 * 60 * 60 * 1000
// Browsers give an origin about 5 MB of localStorage. Pruning before the store is full keeps the
// first write after a long session from paying for the scan.
const PRUNE_ON_START_BYTES = 4 * 1024 * 1024
const FLUSH_DELAY_MS = 1000
const MIN_PRUNE_INTERVAL_MS = 60 * 1000

// Every kea logic path that kea-localstorage writes contains a `<name>Logic.` segment. Keys from
// posthog-js and other libraries do not, so this test keeps pruning away from state that kea does not own.
export function isKeaPersistedKey(key: string): boolean {
    return /Logic\./.test(key)
}

// JavaScript strings are UTF-16, and browsers count localStorage quota in UTF-16 code units.
export function storageEntryBytes(key: string, value: string): number {
    return (key.length + value.length) * 2
}

export interface KeaStorage {
    /** The storage engine to pass to `localStoragePlugin`. kea-localstorage reads and writes it by bracket access. */
    engine: Storage
    lastUsed: () => Record<string, number>
    /** Removes kea-persisted keys not used within the TTL. Returns how many keys it removed. */
    pruneExpired: () => number
    /** Removes every kea-persisted key. Other localStorage keys stay. Returns how many keys it removed. */
    removeAll: () => number
}

interface KeaStorageOptions {
    getStorage?: () => Storage
    now?: () => number
    ttlMs?: number
}

export function createKeaStorage({
    getStorage = () => window.localStorage,
    now = Date.now,
    ttlMs = KEA_STORAGE_TTL_MS,
}: KeaStorageOptions = {}): KeaStorage {
    // The latest value written this session, including writes that localStorage refused. A browser
    // with a full store still serves the older stored value, so reads check this map first. Without
    // it, a reducer reverts to the stale value within the same page load.
    const memory = new Map<string, string>()
    let lastUsed: Record<string, number> = {}
    let flushTimer: ReturnType<typeof setTimeout> | null = null
    let lastPruneAt = -Infinity
    let reportedWriteFailure = false

    const safely = <T>(fn: (storage: Storage) => T, fallback: T): T => {
        // Firefox throws NS_ERROR_FAILURE from every localStorage access, including `window.localStorage`
        // itself, when the origin is denied storage or its storage database is broken.
        try {
            return fn(getStorage())
        } catch {
            return fallback
        }
    }

    const writeThrough = (key: string, value: string): void => {
        try {
            getStorage().setItem(key, value)
            return
        } catch (error) {
            // A full store is the likely cause. Pruning frees space only when expired keys exist, so it
            // runs at most once a minute to keep a store full of live state from scanning on every write.
            if (now() - lastPruneAt >= MIN_PRUNE_INTERVAL_MS && pruneExpired() > 0) {
                if (safely((storage) => (storage.setItem(key, value), true), false)) {
                    return
                }
            }
            if (!reportedWriteFailure) {
                reportedWriteFailure = true
                posthog.captureException(error, { kea_storage_key_count: Object.keys(lastUsed).length })
            }
        }
    }

    const flush = (): void => {
        flushTimer = null
        writeThrough(LAST_USED_STORAGE_KEY, JSON.stringify(lastUsed))
    }

    const touch = (key: string): void => {
        lastUsed[key] = now()
        if (flushTimer === null) {
            flushTimer = setTimeout(flush, FLUSH_DELAY_MS)
        }
    }

    const remove = (keys: string[]): number => {
        for (const key of keys) {
            memory.delete(key)
            delete lastUsed[key]
            safely((storage) => storage.removeItem(key), undefined)
        }
        if (keys.length > 0) {
            flush()
        }
        return keys.length
    }

    const storedKeaKeys = (): string[] =>
        safely((storage) => Object.keys(storage), [] as string[]).filter(isKeaPersistedKey)

    // A key with no recorded use counts as expired. Keys written before this tracking existed have no
    // time, and leaked keys from unmounted logics are never read again to get one. Any key a logic
    // read or wrote this session has a time, so pruning never removes live state.
    const pruneExpired = (): number => {
        lastPruneAt = now()
        const cutoff = now() - ttlMs
        for (const key of Object.keys(lastUsed)) {
            if (lastUsed[key] < cutoff) {
                delete lastUsed[key]
            }
        }
        return remove(storedKeaKeys().filter((key) => (lastUsed[key] ?? 0) < cutoff))
    }

    const removeAll = (): number => remove(storedKeaKeys())

    lastUsed = safely((storage) => JSON.parse(storage.getItem(LAST_USED_STORAGE_KEY) ?? '{}'), {})
    const storedBytes = safely(
        (storage) =>
            Object.keys(storage).reduce((total, key) => total + storageEntryBytes(key, storage.getItem(key) ?? ''), 0),
        0
    )
    if (storedBytes > PRUNE_ON_START_BYTES) {
        pruneExpired()
    }

    const engine = new Proxy({} as Storage, {
        get(_target, key) {
            if (typeof key !== 'string') {
                return undefined
            }
            if (memory.has(key)) {
                touch(key)
                return memory.get(key)
            }
            const value = safely((storage) => storage.getItem(key), null)
            if (value === null) {
                // `undefined`, not `null`, so kea-localstorage treats the key as absent and writes the default.
                return undefined
            }
            touch(key)
            return value
        },
        set(_target, key, value) {
            if (typeof key === 'string') {
                memory.set(key, value)
                touch(key)
                writeThrough(key, value)
            }
            return true
        },
    })

    return { engine, lastUsed: () => lastUsed, pruneExpired, removeAll }
}

export const keaStorage = createKeaStorage()
