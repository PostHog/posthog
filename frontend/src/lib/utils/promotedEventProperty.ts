import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

export function getPromotedPropertyForEvent(
    eventName: string | null | undefined,
    overrides?: Record<string, string | null | undefined>
): string | null {
    if (!eventName) {
        return null
    }
    const override = overrides?.[eventName]
    if (override) {
        return override
    }
    return CORE_FILTER_DEFINITIONS_BY_GROUP.events[eventName]?.promoted_property ?? null
}
