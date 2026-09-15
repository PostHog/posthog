import { ExcludedProperties, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

/**
 * Events whose rows are moving out of the `events` table. A query saved against one of these stops
 * returning data once the move happens, so event pickers leave them out by default.
 *
 * `searchTerms` are every string a search has to equal for us to treat it as a hunt for that event.
 * The label is in there because lists render core events by their label, so "Feature flag called" is
 * a string the user has actually seen and is as likely to type as the raw key.
 */
const EVENTS_HIDDEN_IN_QUERY_BUILDERS: { name: string; searchTerms: string[] }[] = Object.entries(
    CORE_FILTER_DEFINITIONS_BY_GROUP.events
)
    // The "All Events" remap in the taxonomy leaves the '' key holding no definition, so read defensively.
    .filter(([, definition]) => definition?.hidden_in_query_builders)
    .map(([name, definition]) => ({
        name,
        searchTerms: [name, definition.label]
            .filter((term): term is string => typeof term === 'string' && term.length > 0)
            .map((term) => term.toLowerCase()),
    }))

const HIDDEN_EVENT_NAMES = EVENTS_HIDDEN_IN_QUERY_BUILDERS.map(({ name }) => name)

/**
 * Names the Events group adds to its own exclusions.
 *
 * Empty for a picker that passes `includeHiddenEvents`, which is how surfaces that browse captured
 * events (the activity explorer, live events, a group's event feed, ingestion triggers) and the
 * experiment pickers keep offering them.
 */
export function hiddenEventNames(
    featureFlags: Record<string, boolean | string | undefined>,
    includeHiddenEvents?: boolean
): string[] {
    if (includeHiddenEvents || !featureFlags[FEATURE_FLAGS.HIDE_EVENTS_IN_QUERY_BUILDERS]) {
        return []
    }
    return HIDDEN_EVENT_NAMES
}

/**
 * The hidden event this search was looking for, or null. Lets a picker explain an absence it caused
 * rather than reporting no results.
 *
 * Reads the Events group's own exclusions rather than the feature flag, so a picker that opted in,
 * and a user without the flag, both match nothing: a picker only ever explains what it hides itself.
 *
 * Matches the whole query, never a prefix, because "feature" is a plausible real search.
 */
export function hiddenEventMatchingSearch(
    searchQuery: string,
    excludedEventNames: readonly (string | number | null)[] | undefined
): string | null {
    if (!excludedEventNames?.length) {
        return null
    }
    const query = searchQuery.trim().toLowerCase()
    if (!query) {
        return null
    }
    const match = EVENTS_HIDDEN_IN_QUERY_BUILDERS.find(({ searchTerms }) => searchTerms.includes(query))
    return match && excludedEventNames.includes(match.name) ? match.name : null
}

/**
 * The caller's `excludedProperties`, with the hidden names folded into the Events group.
 *
 * The Recent and Pinned tabs read this record rather than the built group's exclusions, so without
 * the names here a pin saved before an event was hidden stays one click from selection. Returns the
 * input unchanged when nothing is hidden, so callers keep a stable reference to memoize on.
 */
export function withHiddenEventsExcluded(
    excludedProperties: ExcludedProperties | undefined,
    featureFlags: Record<string, boolean | string | undefined>,
    includeHiddenEvents?: boolean
): ExcludedProperties | undefined {
    const hidden = hiddenEventNames(featureFlags, includeHiddenEvents)
    if (!hidden.length) {
        return excludedProperties
    }
    return {
        ...excludedProperties,
        [TaxonomicFilterGroupType.Events]: [
            ...(excludedProperties?.[TaxonomicFilterGroupType.Events] ?? []),
            ...hidden,
        ],
    }
}
