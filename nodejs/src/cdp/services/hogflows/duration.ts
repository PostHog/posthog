// One grammar for every duration a workflow expresses: `10d`, `1.5h`, `30m`, `45s`. The sign is parsed
// here because a `delay_until` offset may point before its instant, but nothing else may carry one, so
// unsigned callers reject it rather than quietly accepting `-5d`.
// The alternation keeps each digit run owned by one quantifier. The obvious `\d*\.?\d+` lets two
// quantifiers claim the same digits, so a long non-matching value backtracks quadratically. This form
// matches the same strings linearly. `[0-9]` is the same ASCII grammar the API enforces, spelled the
// same way so the two cannot drift (JS `\d` is already ASCII, but Python's also matches Unicode digits).
const DURATION_REGEX = /^(-?)([0-9]+(?:\.[0-9]+)?|\.[0-9]+)([dhms])$/

export type DurationUnit = 'd' | 'h' | 'm' | 's'

export type ParsedDuration = { amount: number; unit: DurationUnit; negative: boolean }

export const SECONDS_PER_DURATION_UNIT: Record<DurationUnit, number> = { d: 86400, h: 3600, m: 60, s: 1 }

/**
 * The parts of a duration string, or null when it is not one.
 *
 * Returns the parts rather than a total because each caller bounds them differently: a fixed delay
 * clamps the amount per unit, an offset keeps its sign, and a conversion window takes the value whole.
 */
export function parseDuration(value: string): ParsedDuration | null {
    const match = DURATION_REGEX.exec(value)
    if (!match) {
        return null
    }
    const [, sign, amountString, unit] = match
    return { amount: parseFloat(amountString), unit: unit as DurationUnit, negative: sign === '-' }
}

/**
 * Seconds for an unsigned duration, at its full magnitude.
 *
 * Unclamped on purpose. A delay applies per-unit ceilings to bound how long one step waits, and those
 * must not reach a conversion window: `d: 30` there would silently turn a 365-day window into 30 days.
 */
export function durationSeconds(value: string): number | null {
    const parsed = parseDuration(value)
    if (!parsed || parsed.negative) {
        return null
    }
    return parsed.amount * SECONDS_PER_DURATION_UNIT[parsed.unit]
}
