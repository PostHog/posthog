import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

export function hasTaxonomyPromotedProperty(eventName: string | null | undefined): boolean {
    return !!eventName && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[eventName]?.promoted_property
}

/**
 * Resolves the single property whose value a UI should display alongside an event.
 *
 * Taxonomy-configured defaults (e.g. `$pageview` -> `$pathname`) are immutable and
 * always win; team-configured overrides only apply to events that do not have a
 * taxonomy default.
 */
export function getPromotedPropertyForEvent(
    eventName: string | null | undefined,
    overrides?: Record<string, string | null | undefined>
): string | null {
    if (!eventName) {
        return null
    }
    const taxonomyDefault = CORE_FILTER_DEFINITIONS_BY_GROUP.events[eventName]?.promoted_property
    if (taxonomyDefault) {
        return taxonomyDefault
    }
    return overrides?.[eventName] ?? null
}
