import posthog from 'posthog-js'

// kea-localstorage reads and writes its engine with bare property access
// (`engine[path]`), so guarding it needs a Proxy rather than a wrapper object. It
// does that work while a logic mounts, which is during render, so a throw there
// propagates into React and the scene error boundary replaces the whole page.
// Firefox raises a bare NS_ERROR_FAILURE when its storage backend is unavailable,
// so there is no error subtype to match on. Every access degrades instead.
// Scoped to how kea-localstorage reads the engine: enumeration is not proxied, so
// `Object.keys` returns the Storage members rather than the stored keys.

// Read and written through the Proxy as real Storage members rather than as keys
const STORAGE_MEMBERS = new Set(['length', 'clear', 'getItem', 'key', 'removeItem', 'setItem'])

// One report per engine is enough to tell whether storage is failing in the wild.
// Per engine rather than per module, because the app and the toolbar each build
// one and a module global would let the first silence the second for the session
function createFailureReporter(): (error: unknown) => void {
    let reported = false
    return (error: unknown): void => {
        if (reported) {
            return
        }
        reported = true
        try {
            posthog.capture('kea_localstorage_unavailable', { error: String(error) })
        } catch {
            // Telemetry must never be the thing that breaks a render
        }
    }
}

// Arrow functions close over `backing`, so the returned members stay callable
// without rebinding, and no native call escapes a try/catch
function createStorageFacade(backing: Storage | undefined, startupError: unknown): Storage {
    const reportFailureOnce = createFailureReporter()
    // A store at quota rejects writes while its reads keep returning the real
    // values, so a failed write must not condemn the whole store. Failed writes
    // land here and win on read, which keeps the session consistent while every
    // untouched key still comes from the backing store
    const overlay = new Map<string, string>()
    // A store blocked before the engine was built has no failing call to report,
    // because the overlay never throws. Report on first use, which also runs
    // after posthog-js initializes
    const reportUnavailable = (): void => reportFailureOnce(startupError)

    return {
        get length(): number {
            try {
                return backing?.length ?? overlay.size
            } catch (error) {
                reportFailureOnce(error)
                return overlay.size
            }
        },
        clear: (): void => {
            overlay.clear()
            try {
                backing?.clear()
            } catch (error) {
                reportFailureOnce(error)
            }
        },
        getItem: (key: string): string | null => {
            if (overlay.has(key)) {
                return overlay.get(key) ?? null
            }
            if (!backing) {
                reportUnavailable()
                return null
            }
            try {
                return backing.getItem(key)
            } catch (error) {
                reportFailureOnce(error)
                return null
            }
        },
        key: (index: number): string | null => {
            try {
                return backing?.key(index) ?? null
            } catch (error) {
                reportFailureOnce(error)
                return null
            }
        },
        removeItem: (key: string): void => {
            overlay.delete(key)
            try {
                backing?.removeItem(key)
            } catch (error) {
                reportFailureOnce(error)
            }
        },
        setItem: (key: string, value: string): void => {
            const stored = String(value)
            if (!backing) {
                reportUnavailable()
                overlay.set(key, stored)
                return
            }
            try {
                backing.setItem(key, stored)
                // The backing store holds the value now, so the overlay must stop
                // shadowing it
                overlay.delete(key)
            } catch (error) {
                reportFailureOnce(error)
                // The value survives this session even though it never reaches disk
                overlay.set(key, stored)
            }
        },
    }
}

export function createSafeStorageEngine(backing: Storage | undefined, startupError?: unknown): Storage {
    const facade = createStorageFacade(backing, startupError)
    return new Proxy(facade, {
        get: (target, prop) =>
            typeof prop === 'string' && !STORAGE_MEMBERS.has(prop)
                ? // Native property access yields undefined for a missing key while
                  // getItem yields null, and kea-localstorage branches on
                  // `typeof engine[path] !== 'undefined'`. Returning null here would
                  // load null over every persisted reducer's coded default
                  (target.getItem(prop) ?? undefined)
                : Reflect.get(target, prop),
        set: (target, prop, value) => {
            if (typeof prop === 'string' && !STORAGE_MEMBERS.has(prop)) {
                target.setItem(prop, String(value))
            }
            return true
        },
        has: (target, prop) =>
            typeof prop === 'string' && !STORAGE_MEMBERS.has(prop)
                ? target.getItem(prop) !== null
                : Reflect.has(target, prop),
        deleteProperty: (target, prop) => {
            if (typeof prop === 'string' && !STORAGE_MEMBERS.has(prop)) {
                target.removeItem(prop)
            }
            return true
        },
    })
}

export function resolveLocalStorage(): { storage: Storage | undefined; error?: unknown } {
    try {
        const storage = window.localStorage
        // Reading proves the object is usable. A write probe would reject a store
        // sitting at quota, whose reads still return every saved value, and each
        // persisted reducer would then load its default over readable state
        void storage.length
        return { storage }
    } catch (error) {
        // Blocked outright, so every access falls back to the overlay and
        // persistence still works for the rest of the session. Keep the error so
        // the first key access reports it - a full store, blocked site data, and
        // Safari private mode all fail here, and those are the common causes
        return { storage: undefined, error }
    }
}

const resolvedLocalStorage = resolveLocalStorage()
export const safeStorageEngine = createSafeStorageEngine(resolvedLocalStorage.storage, resolvedLocalStorage.error)
