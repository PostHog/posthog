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
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : 0
    }
    if (typeof value === 'string' && value.length > 0) {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : 0
    }
    return 0
}
