import { PluginEvent } from '~/plugin-scaffold'

/**
 * Read a numeric property from the event's properties bag, returning zero for
 * any value that is missing, non-finite, or not numeric. Accepts numeric
 * strings (e.g. `"100"`) as well as numbers — third-party SDKs and OTel
 * collectors occasionally serialise token counts as strings, and the cost
 * pipeline must bill those tokens correctly rather than silently zeroing them.
 */
export const numericProperty = (event: PluginEvent, key: string): number => {
    const value = event.properties?.[key]
    return finiteNumberOrUndefined(value) ?? 0
}

/**
 * Coerce a raw property value to a finite number, returning `undefined` for any
 * value that is missing, non-finite, or not numeric. Accepts numeric strings
 * (e.g. `"0.001"`) like {@link numericProperty}. Unlike `numericProperty`, this
 * distinguishes "absent or invalid" from a legitimate `0`, so callers can fall
 * back to a different pricing source rather than billing at a rate of zero.
 * Used to sanitise custom token prices (`$ai_input_token_price` etc.) before
 * they reach `js-big-decimal`, which throws `Parameter is not a number` on any
 * non-numeric input.
 */
export const finiteNumberOrUndefined = (value: unknown): number | undefined => {
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : undefined
    }
    if (typeof value === 'string' && value.length > 0) {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : undefined
    }
    return undefined
}
