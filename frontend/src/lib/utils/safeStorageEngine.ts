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

export function createSafeStorageEngine(backing: Storage | undefined): Storage {
    const facade = createStorageFacade(backing ?? createMemoryStorage())
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

function resolveLocalStorage(): Storage | undefined {
    try {
        const probe = '__safe_storage_probe__'
        window.localStorage.setItem(probe, probe)
        window.localStorage.removeItem(probe)
        return window.localStorage
    } catch {
        // Blocked outright, so fall back to memory and keep persistence
        // working for the rest of the session
        return undefined
    }
}

export const safeStorageEngine = createSafeStorageEngine(resolveLocalStorage())
