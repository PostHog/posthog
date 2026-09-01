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

let failureReported = false

// Once per session is enough to tell whether storage is failing in the wild.
// Without it, degrading silently would also hide the problem from us
function reportFailureOnce(error: unknown): void {
    if (failureReported) {
        return
    }
    failureReported = true
    try {
        posthog.capture('kea_localstorage_unavailable', { error: String(error) })
    } catch {
        // Telemetry must never be the thing that breaks a render
    }
}

function createMemoryStorage(): Storage {
    const values = new Map<string, string>()
    return {
        get length(): number {
            return values.size
        },
        clear: (): void => values.clear(),
        getItem: (key: string): string | null => values.get(key) ?? null,
        key: (index: number): string | null => Array.from(values.keys())[index] ?? null,
        removeItem: (key: string): void => void values.delete(key),
        setItem: (key: string, value: string): void => void values.set(key, String(value)),
    }
}

// Arrow functions close over `backing`, so the returned members stay callable
// without rebinding, and no native call escapes a try/catch
function createStorageFacade(backing: Storage): Storage {
    return {
        get length(): number {
            try {
                return backing.length
            } catch (error) {
                reportFailureOnce(error)
                return 0
            }
        },
        clear: (): void => {
            try {
                backing.clear()
            } catch (error) {
                reportFailureOnce(error)
            }
        },
        getItem: (key: string): string | null => {
            try {
                return backing.getItem(key)
            } catch (error) {
                reportFailureOnce(error)
                return null
            }
        },
        key: (index: number): string | null => {
            try {
                return backing.key(index)
            } catch (error) {
                reportFailureOnce(error)
                return null
            }
        },
        removeItem: (key: string): void => {
            try {
                backing.removeItem(key)
            } catch (error) {
                reportFailureOnce(error)
            }
        },
        setItem: (key: string, value: string): void => {
            try {
                backing.setItem(key, String(value))
            } catch (error) {
                reportFailureOnce(error)
                // A full or unavailable store means the value is not remembered.
                // Losing persistence is the intended trade against losing the scene
            }
        },
    }
}

export function createSafeStorageEngine(backing: Storage | undefined, startupError?: unknown): Storage {
    const facade = createStorageFacade(backing ?? createMemoryStorage())
    // A store blocked at startup fails the probe and drops to the memory fallback, which never
    // throws, so no facade catch can report it. resolveLocalStorage() also runs at module load,
    // before posthog-js is initialized, so a capture there would be lost. Report on the first
    // real key access instead - that runs during a logic mount, after posthog-js is up.
    let startupPending = startupError !== undefined
    const reportStartupFailureOnce = (): void => {
        if (startupPending) {
            startupPending = false
            reportFailureOnce(startupError)
        }
    }
    return new Proxy(facade, {
        get: (target, prop) => {
            if (typeof prop === 'string' && !STORAGE_MEMBERS.has(prop)) {
                reportStartupFailureOnce()
                // Native property access yields undefined for a missing key while
                // getItem yields null, and kea-localstorage branches on
                // `typeof engine[path] !== 'undefined'`. Returning null here would
                // load null over every persisted reducer's coded default
                return target.getItem(prop) ?? undefined
            }
            return Reflect.get(target, prop)
        },
        set: (target, prop, value) => {
            if (typeof prop === 'string' && !STORAGE_MEMBERS.has(prop)) {
                reportStartupFailureOnce()
                target.setItem(prop, String(value))
            }
            return true
        },
        has: (target, prop) => {
            if (typeof prop === 'string' && !STORAGE_MEMBERS.has(prop)) {
                reportStartupFailureOnce()
                return target.getItem(prop) !== null
            }
            return Reflect.has(target, prop)
        },
        deleteProperty: (target, prop) => {
            if (typeof prop === 'string' && !STORAGE_MEMBERS.has(prop)) {
                reportStartupFailureOnce()
                target.removeItem(prop)
            }
            return true
        },
    })
}

function resolveLocalStorage(): { storage: Storage | undefined; error?: unknown } {
    try {
        const probe = '__safe_storage_probe__'
        window.localStorage.setItem(probe, probe)
        window.localStorage.removeItem(probe)
        return { storage: window.localStorage }
    } catch (error) {
        // Blocked outright, so fall back to memory and keep persistence working for the rest of
        // the session. Keep the error so the first key access reports it - a full store, blocked
        // site data, and Safari private mode all fail here, and those are the common causes
        return { storage: undefined, error }
    }
}

const resolvedLocalStorage = resolveLocalStorage()
export const safeStorageEngine = createSafeStorageEngine(resolvedLocalStorage.storage, resolvedLocalStorage.error)
