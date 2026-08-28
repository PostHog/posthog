// kea-localstorage reads and writes persisted reducers through bracket access on a
// storage object (`engine[path]`), not through `getItem`/`setItem`. Firefox can throw a
// bare `NS_ERROR_FAILURE` from every localStorage access when the origin is denied storage
// or its storage database is broken. Because logics build lazily during React render, that
// throw escapes the scene boundary and blanks the whole app.
//
// This Proxy wraps every access in try/catch and falls back to an in-memory Map, so a
// persisted reducer degrades to non-persistent instead of killing the app.
export function createGuardedStorageEngine(): Storage {
    const memory = new Map<string, string>()

    return new Proxy({} as Storage, {
        get(_target, prop) {
            if (typeof prop !== 'string') {
                return undefined
            }
            try {
                const value = window.localStorage.getItem(prop)
                if (value !== null) {
                    return value
                }
            } catch {
                // fall through to the in-memory copy
            }
            // `undefined` (not `null`) so kea-localstorage treats a missing key as absent
            return memory.get(prop)
        },
        set(_target, prop, value) {
            if (typeof prop === 'string') {
                try {
                    window.localStorage.setItem(prop, value)
                } catch {
                    memory.set(prop, value)
                }
            }
            return true
        },
    })
}
