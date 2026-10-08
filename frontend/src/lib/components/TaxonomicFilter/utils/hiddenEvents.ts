import { ExcludedProperties, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

const EVENTS_MODE = FlagEvaluationsModeEnumApi.Number0

/**
 * Events whose rows are moving out of the `events` table. Event pickers leave them out, because a
 * query saved against one stops returning data once the move happens.
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
 * Empty when the team's `flag_evaluations_mode` is Events or missing, or when the picker passes
 * `includeHiddenEvents`. Surfaces that browse captured events (the activity explorer, live events, a
 * group's event feed, ingestion triggers) and the experiment pickers pass it.
 *
 * For an organization on mode 1, the team API reports Events while the
 * `FLAG_EVALUATIONS_USAGE_TAB_FORCE_EVENTS` instance setting is on, so its pickers show these events again.
 */
export function hiddenEventNames(
    flagEvaluationsMode: FlagEvaluationsModeEnumApi | undefined,
    includeHiddenEvents?: boolean
): string[] {
    if (includeHiddenEvents || (flagEvaluationsMode ?? EVENTS_MODE) === EVENTS_MODE) {
        return []
    }
    return HIDDEN_EVENT_NAMES
}

/**
 * The hidden event this search was looking for, or null. Lets a picker explain an absence it caused
 * rather than reporting no results.
 *
 * Reads the Events group's own exclusions rather than the team's mode, so a picker only explains what
 * it hides itself.
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
    flagEvaluationsMode: FlagEvaluationsModeEnumApi | undefined,
    includeHiddenEvents?: boolean
): ExcludedProperties | undefined {
    const hidden = hiddenEventNames(flagEvaluationsMode, includeHiddenEvents)
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
