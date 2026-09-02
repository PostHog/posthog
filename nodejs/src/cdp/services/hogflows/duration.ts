// Duration strings as workflow steps already express them: `10d`, `1.5h`, `30m`, `45s`.
export const DURATION_REGEX = /^(\d*\.?\d+)([dhms])$/

export const SECONDS_PER_DURATION_UNIT: Record<string, number> = { d: 86400, h: 3600, m: 60, s: 1 }

/**
 * Seconds for a duration string, or null when it is not one.
 *
 * Unclamped on purpose. A delay applies its own per-unit ceilings to bound how long one step waits, and
 * those must not reach a conversion window: `d: 30` there would silently turn a 365-day window into a
 * 30-day one.
 */
export function durationSeconds(value: string): number | null {
    const match = DURATION_REGEX.exec(value)
    if (!match) {
        return null
    }
    const [, amountString, unit] = match
    return parseFloat(amountString) * SECONDS_PER_DURATION_UNIT[unit]
}
