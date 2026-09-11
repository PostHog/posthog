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
            // The in-memory copy holds the latest value written this session, including a
            // write localStorage refused. A quota-blocked browser can still serve stale
            // reads, so prefer memory to avoid returning a value the write already replaced.
            if (memory.has(prop)) {
                return memory.get(prop)
            }
            try {
                const value = window.localStorage.getItem(prop)
                if (value !== null) {
                    return value
                }
            } catch {
                // fall through to the missing-key result
            }
            // `undefined` (not `null`) so kea-localstorage treats a missing key as absent
            return undefined
        },
        set(_target, prop, value) {
            if (typeof prop === 'string') {
                // Always mirror into memory so a later read stays consistent with this
                // write, even when localStorage refuses it (quota) but reads still succeed.
                memory.set(prop, value)
                try {
                    window.localStorage.setItem(prop, value)
                } catch {
                    // localStorage refused the write; the in-memory copy above keeps the
                    // session consistent.
                }
            }
            return true
        },
    })
}
