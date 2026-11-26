const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

function later(count: number, unit: string): string {
    return `${count} ${count === 1 ? unit : `${unit}s`} later`
}

// The unit follows the rounded value, so a silence just under an hour reads "1 hour later", never "60 minutes later".
export function formatSilence(ms: number): string {
    const minutes = Math.round(ms / MINUTE_MS)
    if (minutes < HOUR_MS / MINUTE_MS) {
        return later(minutes, 'minute')
    }
    const hours = Math.round(ms / HOUR_MS)
    if (hours < DAY_MS / HOUR_MS) {
        return later(hours, 'hour')
    }
    return later(Math.round(ms / DAY_MS), 'day')
}
