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

/**
 * Coerce a raw property value to a finite number, or `undefined` when it isn't
 * one. Unlike {@link numericProperty} this keeps "absent or unusable" distinct
 * from a legitimate `0`, so callers can fall back to another pricing source
 * instead of billing at a rate of zero. Everything reaching `js-big-decimal`
 * must pass through here first — it throws on operands it can't parse.
 */
export const finiteNumberOrUndefined = (value: unknown): number | undefined => {
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : undefined
    }
    if (typeof value === 'string') {
        // Number(' ') is 0, so a blank string would otherwise bill at rate zero.
        const trimmed = value.trim()
        if (trimmed.length === 0) {
            return undefined
        }
        const parsed = Number(trimmed)
        return Number.isFinite(parsed) ? parsed : undefined
    }
    return undefined
}
