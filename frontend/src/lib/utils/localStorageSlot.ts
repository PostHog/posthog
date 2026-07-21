import { z } from 'zod'

export interface LocalStorageSlot<T> {
    get: () => T | null
    set: (value: T) => void
}

// Stored data outlives deploys and can be edited by hand, so reads validate
// against the schema before trusting it
export function localStorageSlot<T>(key: string, schema: z.ZodType<T>): LocalStorageSlot<T> {
    return {
        get: (): T | null => {
            try {
                const raw = localStorage.getItem(key)
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
                localStorage.setItem(key, JSON.stringify(value))
            } catch {
                // localStorage can be unavailable. Losing the value is fine
            }
        },
    }
}
