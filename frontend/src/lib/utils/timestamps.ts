/**
 * Parse timestamp strings of form "1:23" or "00:01:23" into milliseconds
 * @param input - Timestamp string
 * @returns Number of milliseconds, or undefined if invalid
 */
export function parseTimestampToMs(input?: string | null): number | undefined {
    if (!input) {
        return undefined
    }
    const value = String(input).trim()
    if (!value) {
        return undefined
    }

    // Handle mm:ss or hh:mm:ss format
    const parts = value.split(':').map((p) => parseInt(p, 10))
    if (parts.every((n) => !Number.isNaN(n))) {
        let seconds = 0
        if (parts.length === 2) {
            const [mm, ss] = parts
            seconds = mm * 60 + ss
        } else if (parts.length === 3) {
            const [hh, mm, ss] = parts
            seconds = hh * 3600 + mm * 60 + ss
        }
        if (seconds > 0) {
            return seconds * 1000
        }
    }
    return undefined
}
