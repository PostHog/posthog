/**
 * Values that survive a reload of this browser tab and nothing longer, so a later visit starts fresh.
 * Storage can be blocked or full. Reads then return null and writes do nothing, which leaves the default state.
 */
export function readSessionValue<T>(key: string): T | null {
    try {
        const raw = sessionStorage.getItem(key)
        return raw ? (JSON.parse(raw) as T) : null
    } catch {
        return null
    }
}

export function writeSessionValue<T>(key: string, value: T | null): void {
    try {
        if (value === null) {
            sessionStorage.removeItem(key)
        } else {
            sessionStorage.setItem(key, JSON.stringify(value))
        }
    } catch {
        return
    }
}
