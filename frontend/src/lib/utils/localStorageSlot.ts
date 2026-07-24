import { z } from 'zod'

export interface LocalStorageSlot<T> {
    get: () => T | null
    set: (value: T) => void
}

// Stored data outlives deploys and can be edited by hand, so reads validate
// against the schema before trusting it. A function key is resolved on every
// access, for keys that depend on runtime context (e.g. the current team)
export function localStorageSlot<T>(key: string | (() => string), schema: z.ZodType<T>): LocalStorageSlot<T> {
    const resolveKey = (): string => (typeof key === 'function' ? key() : key)
    return {
        get: (): T | null => {
            try {
                const raw = localStorage.getItem(resolveKey())
                if (!raw) {
                    return null
                }
                const result = schema.safeParse(JSON.parse(raw))
                return result.success ? result.data : null
            } catch {
                return null
            }
        },
        set: (value: T): void => {
            try {
                localStorage.setItem(resolveKey(), JSON.stringify(value))
            } catch {
                // localStorage can be unavailable. Losing the value is fine
            }
        },
    }
}
