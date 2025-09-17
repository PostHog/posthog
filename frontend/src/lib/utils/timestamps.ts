/**
 * Parse timestamp strings of form "1:23" or "00:01:23" into milliseconds
 * @param input - Timestamp string
 * @returns Number of milliseconds, or undefined if invalid
 */
export function parseTimestampToMs(input?: string | null): number | undefined {
    if (input == null) {
        return undefined
    }
    const value = String(input).trim()
    if (!value.length) {
        return undefined
    }

    // Handle mm:ss or hh:mm:ss format
    const parts = value.split(':').map((p) => Number(p))
    if (parts.length > 1 && parts.length <= 3 && parts.every((n) => Number.isSafeInteger(n) && n >= 0)) {
        let seconds = 0
        if (parts.length === 2) {
            const [mm, ss] = parts
            seconds = mm * 60 + ss
        } else if (parts.length === 3) {
            const [hh, mm, ss] = parts
            seconds = hh * 3600 + mm * 60 + ss
        }
        return seconds * 1000
    }
    return undefined
}
