import { ExcludedProperties, HiddenEventStandIn, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, deriveFromCoreFilterDefinitions } from '~/taxonomy/taxonomy'

const EVENTS_MODE = FlagEvaluationsModeEnumApi.Number0

const REACHES_SECOND_WORD = /[_\s]\S/

/**
 * Events whose rows are moving out of the `events` table. Event pickers leave them out, because a
 * query saved against one stops returning data once the move happens.
 *
 * `searchTerms` are every string a search has to equal for us to treat it as a hunt for that event.
 * The label is in there because lists render core events by their label, so "Feature flag called" is
 * a string the user has actually seen and is as likely to type as the raw key.
 *
 * `standInPrefixTerms` add the name without its `$`, because the posthog.com docs write the event that way.
 */
const eventsHiddenInQueryBuilders = deriveFromCoreFilterDefinitions(
    (): { name: string; searchTerms: string[]; standInPrefixTerms: string[] }[] =>
        Object.entries(CORE_FILTER_DEFINITIONS_BY_GROUP.events)
            // The "All Events" remap in the taxonomy leaves the '' key holding no definition, so read defensively.
            .filter(([, definition]) => definition?.hidden_in_query_builders)
            .map(([name, definition]) => {
                const searchTerms = [name, definition.label]
                    .filter((term): term is string => typeof term === 'string' && term.length > 0)
                    .map((term) => term.toLowerCase())
                return {
                    name,
                    searchTerms,
                    standInPrefixTerms: [...searchTerms, name.replace(/^\$/, '').toLowerCase()],
                }
            })
)

const hiddenEventNamesInTaxonomy = deriveFromCoreFilterDefinitions((): string[] =>
    eventsHiddenInQueryBuilders().map(({ name }) => name)
)

/**
 * Names the Events group adds to its own exclusions.
 *
 * Empty when the team's `flag_evaluations_mode` is Events or missing, or when the picker passes
 * `includeHiddenEvents`. `TaxonomicFilterProps.includeHiddenEvents` says which pickers pass it.
 *
 * For an organization on mode 1, the team API reports Events while the
 * `FLAG_EVALUATIONS_READS_FORCE_EVENTS` instance setting is on, so its pickers show these events again.
 *
 * Every hidden name when the group offers stand-ins, whatever `includeHiddenEvents` says. The stand-in row then
 * replaces the event's own row, so a definition the team still has does not list the event twice.
 */
export function hiddenEventNames(
    flagEvaluationsMode: FlagEvaluationsModeEnumApi | undefined,
    includeHiddenEvents?: boolean,
    offerHiddenEventStandIns?: boolean
): string[] {
    const hides =
        offerHiddenEventStandIns || (!includeHiddenEvents && (flagEvaluationsMode ?? EVENTS_MODE) !== EVENTS_MODE)
    return hides ? hiddenEventNamesInTaxonomy() : []
}

/**
 * Unlike `hiddenEventMatchingSearch`, this matches a prefix, so "feature flag" finds the event.
 * The prefix has to reach the second word of the name or label. The stand-in leads the list, and a search for
 * "feature" or "$feature_" must keep a real event such as `$feature_view` at row 0.
 */
export function hiddenEventStandInsMatchingSearch(
    searchQuery: string,
    excludedEventNames?: readonly unknown[]
): HiddenEventStandIn[] {
    const query = searchQuery.trim().toLowerCase()
    if (!REACHES_SECOND_WORD.test(query)) {
        return []
    }
    return eventsHiddenInQueryBuilders()
        .filter(
            ({ name, standInPrefixTerms }) =>
                !excludedEventNames?.includes(name) && standInPrefixTerms.some((term) => term.startsWith(query))
        )
        .map(({ name }) => ({ _type: 'hidden_event_stand_in', name, value: name }))
}

/** The https link in the move notices flag's payload, or null while there is no announcement to link to. */
export function moveAnnouncementUrl(payload: unknown): string | null {
    const url = typeof payload === 'object' && payload !== null && 'url' in payload ? payload.url : null
    if (typeof url !== 'string') {
        return null
    }
    try {
        const { protocol, host } = new URL(url)
        return protocol === 'https:' && host ? url : null
    } catch {
        return null
    }
}

/** The hidden events that a mode 0 action or cohort editor warns about. Empty until the move is announced. */
export function eventsWithMoveNotice(
    flagEvaluationsMode: FlagEvaluationsModeEnumApi | undefined,
    moveNoticesEnabled: boolean
): string[] {
    return moveNoticesEnabled && (flagEvaluationsMode ?? EVENTS_MODE) === EVENTS_MODE
        ? hiddenEventNamesInTaxonomy()
        : []
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
    const match = eventsHiddenInQueryBuilders().find(({ searchTerms }) => searchTerms.includes(query))
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
