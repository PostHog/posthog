import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

export function hasTaxonomyPrimaryProperty(eventName: string | null | undefined): boolean {
    return !!eventName && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[eventName]?.primary_property
}

/**
 * Resolves the single property whose value a UI should display alongside an event.
 *
 * Taxonomy-configured defaults (e.g. `$pageview` -> `$pathname`) are immutable and
 * always win; team-configured overrides only apply to events that do not have a
 * taxonomy default.
 *
 * This is a pure client-side lookup — both the taxonomy and the overrides map are
 * already in memory, so callers can invoke this in tight loops (e.g. selectors
 * filtering all events in a session) without n+1 risk.
 */
export function getPrimaryPropertyForEvent(
    eventName: string | null | undefined,
    overrides?: Record<string, string | null | undefined>
): string | null {
    if (!eventName) {
        return null
    }
    const taxonomyDefault = CORE_FILTER_DEFINITIONS_BY_GROUP.events[eventName]?.primary_property
    if (taxonomyDefault) {
        return taxonomyDefault
    }
    return overrides?.[eventName] ?? null
}

/**
 * Filters a list of events down to those that have a primary property
 * (taxonomy default or team override). Pure client-side — wraps
 * `getPrimaryPropertyForEvent` so the intent reads as one operation.
 */
export function getEventsWithPrimaryProperty<T extends { event: string }>(
    events: T[],
    overrides?: Record<string, string | null | undefined>
): T[] {
    return events.filter((e) => getPrimaryPropertyForEvent(e.event, overrides) !== null)
}
