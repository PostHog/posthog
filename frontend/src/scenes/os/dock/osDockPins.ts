// pinned: localStorage key prefix, renaming it drops every pinned dock app
const STORAGE_KEY_PREFIX = 'posthog-os-dock:'
const STORAGE_VERSION = 1
// Bounds what a corrupted or hand-edited entry can make the dock hold.
export const OS_DOCK_MAX_PINS = 100
const MAX_KEY_LENGTH = 200

export function osDockPinsStorageKey(teamId: number | null): string | null {
    return teamId ? `${STORAGE_KEY_PREFIX}${teamId}` : null
}

/** The pinned app keys saved for a project. Anything that does not parse reads as no pins. */
export function readOsDockPins(teamId: number | null): string[] {
    const key = osDockPinsStorageKey(teamId)
    if (!key) {
        return []
    }
    try {
        const parsed = JSON.parse(localStorage.getItem(key) ?? 'null')
        if (!parsed || parsed.version !== STORAGE_VERSION || !Array.isArray(parsed.keys)) {
            return []
        }
        const keys = (parsed.keys as unknown[]).filter(
            (value): value is string => typeof value === 'string' && value.length > 0 && value.length <= MAX_KEY_LENGTH
        )
        return [...new Set(keys)].slice(0, OS_DOCK_MAX_PINS)
    } catch {
        return []
    }
}

export function writeOsDockPins(teamId: number | null, keys: string[]): void {
    const key = osDockPinsStorageKey(teamId)
    if (!key) {
        return
    }
    try {
        localStorage.setItem(key, JSON.stringify({ version: STORAGE_VERSION, keys }))
    } catch {
        // A full or blocked localStorage only costs the pins after a reload, so the dock keeps working.
    }
}
