import { PluginEvent } from '~/plugin-scaffold'

/**
 * Read a numeric property from the event's properties bag, defaulting to zero.
 * Numeric strings count as numbers — third-party SDKs and OTel collectors
 * occasionally serialize token counts as strings, and the cost pipeline must
 * bill those tokens rather than silently zeroing them.
 */
export const numericProperty = (event: PluginEvent, key: string): number => {
    return finiteNumberOrUndefined(event.properties?.[key]) ?? 0
}

// Deliberately narrower than `Number()`, which reads `'0x10'` as 16, `''` as 0 and
// `' '` as 0. Billing can't invent a rate out of a radix prefix or a blank string,
// and `js-big-decimal` reads both into `NaN` digits anyway.
const DECIMAL_NUMBER = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/

/**
 * Coerce a raw property value to a finite number, or `undefined` when it isn't
 * one. Unlike {@link numericProperty} this keeps "absent or unusable" distinct
 * from a legitimate `0`, so callers can fall back to another pricing source
 * instead of billing at a rate of zero.
 *
 * Everything reaching `js-big-decimal` must pass through here first, and must use
 * the number this returns rather than the original value: the library parses its
 * operands character by character, so a string it disagrees with becomes a
 * `'NaN10'`-style result that either throws downstream or lands in ClickHouse as
 * the cost.
 */
export const finiteNumberOrUndefined = (value: unknown): number | undefined => {
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : undefined
    }
    if (typeof value === 'string' && DECIMAL_NUMBER.test(value.trim())) {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : undefined
    }
    return undefined
}
