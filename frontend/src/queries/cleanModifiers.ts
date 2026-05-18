// Modifier keys that have been removed from `HogQLQueryModifiers` server-side
// but may still be present in queries persisted before the removal — saved
// insights, bookmarks, the activity-explorer URL hash, etc. The server's
// `HogQLQueryModifiers` model is `extra='forbid'`, so any unknown key fails
// request validation and the user sees an empty result set instead of their
// events. Strip these before the query is rehydrated so stale state never
// reaches the validator.
const DEPRECATED_MODIFIER_KEYS = new Set<string>(['usePresortedEventsTable'])

/**
 * Recursively walk a value and strip deprecated keys out of any nested
 * `modifiers` object. Returns a cleaned copy — never mutates the input. Safe
 * to call on arbitrary JSON payloads, including ones that aren't valid query
 * nodes.
 */
export function cleanModifiers<T>(value: T): T {
    if (Array.isArray(value)) {
        return value.map((item) => cleanModifiers(item)) as unknown as T
    }
    if (value && typeof value === 'object') {
        const result: Record<string, unknown> = {}
        for (const [key, nested] of Object.entries(value)) {
            if (key === 'modifiers' && nested && typeof nested === 'object' && !Array.isArray(nested)) {
                const cleaned: Record<string, unknown> = {}
                for (const [modKey, modValue] of Object.entries(nested)) {
                    if (!DEPRECATED_MODIFIER_KEYS.has(modKey)) {
                        cleaned[modKey] = modValue
                    }
                }
                result[key] = cleaned
            } else {
                result[key] = cleanModifiers(nested)
            }
        }
        return result as T
    }
    return value
}
