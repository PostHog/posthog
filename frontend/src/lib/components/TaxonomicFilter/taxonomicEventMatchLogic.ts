import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import { taxonomicSearchIntentMatchEventsCreate } from '~/generated/core/api'
import type { EventMatchApi, EventMatchOutcomeEnumApi } from '~/generated/core/api.schemas'

import type { FeatureFlagsSet } from '../../logic/featureFlagLogic'
import { SelectItemMeta, taxonomicFilterLogic } from './taxonomicFilterLogic'
import { legacyTaxonomicSurface } from './taxonomicFilterSurface'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from './types'

// Mirrors MIN_QUERY_CHARS and MAX_QUERY_CHARS in posthog/taxonomic_search_intent/classify.py.
const MIN_QUERY_LENGTH = 2
const MAX_QUERY_LENGTH = 64
// Mirrors MAX_MATCHES in posthog/taxonomic_search_intent/event_match.py. Applied after exclusions, so they never empty the list.
const MAX_SUGGESTIONS = 3
// Longer than a keystroke gap, so a person who types a phrase asks once and not once per letter.
const EVENT_MATCH_DEBOUNCE_MS = 350
// A throttle returns 429 by design, and the backend reports its own model failures as 503.
// Other failures are visible only in the browser, so the logic reports them without the search text.
const UNREPORTED_FAILURE_STATUSES = [429, 503]
// The picker keeps every tab's list mounted and hides the inactive ones, so only the open tab may ask the model.
const TABS_WITH_SUGGESTIONS = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.SuggestedFilters]
// The flag is an experiment. Only the test arm asks the model; both arms report that they reached the dead end.
const EXPERIMENT_VARIANTS = ['control', 'test']
const TEST_VARIANT = 'test'

export interface EventMatchAnswer {
    matches: EventMatchApi[]
    outcome: EventMatchOutcomeEnumApi
    unsent: EventMatchApi[]
}

export interface EventMatches extends EventMatchAnswer {
    projectId: number
    query: string
}

/** What the empty state can say when the model has no event to suggest. */
export type EventMatchHint = { kind: 'unsent'; events: EventMatchApi[] } | { kind: 'value' }

// A 404 means the person is not in the flag for this project, so the rest of the page load does not ask again.
const unavailableProjectIds = new Set<number>()
// Switching between the All and Events tabs remounts the empty state and this logic with it, so each answer is
// kept for the page load and shown again without another model call. The backend caches the same key.
const answeredMatches = new Map<string, EventMatchAnswer>()
// Exposure for the experiment: one report per search per page load, so retyping or remounting does not count twice.
const reportedEligible = new Set<string>()

const matchKey = (projectId: number, query: string): string => `${projectId}:${query}`

// A value belongs to a property, so the value hint only helps in a picker where the person can pick one.
const PROPERTY_GROUP_TYPES = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.SessionProperties,
]

function offersProperties(taxonomicGroupTypes: TaxonomicFilterGroupType[]): boolean {
    return PROPERTY_GROUP_TYPES.some((groupType) => taxonomicGroupTypes.includes(groupType))
}

export function resetEventMatchMemoryForTests(): void {
    unavailableProjectIds.clear()
    answeredMatches.clear()
    reportedEligible.clear()
}

function reportEligible(projectId: number, query: string, tab: TaxonomicFilterGroupType, variant: string): void {
    const key = matchKey(projectId, query)
    if (reportedEligible.has(key)) {
        return
    }
    reportedEligible.add(key)
    // pinned: analytics event name and properties, the experiment's exposure reads them
    posthog.capture('taxonomic filter event match eligible', {
        surface: legacyTaxonomicSurface(),
        tab,
        variant,
    })
}

function reportHint(hint: EventMatchHint | null, tab: TaxonomicFilterGroupType): void {
    if (!hint) {
        return
    }
    posthog.capture('taxonomic filter event match hint shown', {
        surface: legacyTaxonomicSurface(),
        tab,
        hint: hint.kind,
        unsentEvents: hint.kind === 'unsent' ? hint.events.map((event) => event.name) : undefined,
    })
}

function reportSuggested(shown: EventMatchApi[], tab: TaxonomicFilterGroupType): void {
    // Only the suggestions the picker shows, after its exclusions, count for the flag's metric.
    if (shown.length === 0) {
        return
    }
    // pinned: analytics event name and properties, the flag's success metric reads them
    posthog.capture('taxonomic filter event match suggested', {
        surface: legacyTaxonomicSurface(),
        tab,
        suggestedEvents: shown.map((match) => match.name),
    })
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface taxonomicEventMatchLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentProjectId: number | null // projectLogic
    activeTab: TaxonomicFilterGroupType // taxonomicFilterLogic
    searchQuery: string // taxonomicFilterLogic
    taxonomicGroupTypes: TaxonomicFilterGroupType[] // taxonomicFilterLogic
    taxonomicGroups: TaxonomicFilterGroup[] // taxonomicFilterLogic
    currentAnswer: EventMatches | null
    eventMatches: EventMatches | null
    hint: EventMatchHint | null
    isMatching: boolean
    pendingQuery: string | null
    suggestedEvents: EventMatchApi[]
    tabShowsSuggestions: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface taxonomicEventMatchLogicActions {
    selectItem: (
        group: TaxonomicFilterGroup,
        value: TaxonomicFilterValue,
        item: any,
        meta?: SelectItemMeta | undefined
    ) => {
        group: TaxonomicFilterGroup
        item: any
        meta: SelectItemMeta | undefined
        value: TaxonomicFilterValue
    } // taxonomicFilterLogic
    setSearchQuery: (searchQuery: string) => {
        searchQuery: string
    } // taxonomicFilterLogic
    findEventMatches: (searchQuery: string) => {
        searchQuery: string
    }
    selectEventMatch: (match: EventMatchApi) => {
        match: EventMatchApi
    }
    setEventMatches: (eventMatches: EventMatches | null) => {
        eventMatches: EventMatches | null
    }
    startEventMatch: (query: string) => {
        query: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface taxonomicEventMatchLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        currentAnswer: (
            eventMatches: EventMatches | null,
            searchQuery: string,
            currentProjectId: number | null
        ) => EventMatches | null
        hint: (
            currentAnswer: EventMatches | null,
            suggestedEvents: EventMatchApi[],
            taxonomicGroups: TaxonomicFilterGroup[],
            taxonomicGroupTypes: TaxonomicFilterGroupType[]
        ) => EventMatchHint | null
        suggestedEvents: (
            currentAnswer: EventMatches | null,
            taxonomicGroups: TaxonomicFilterGroup[]
        ) => EventMatchApi[]
        isMatching: (pendingQuery: string | null, searchQuery: string) => boolean
        tabShowsSuggestions: (activeTab: TaxonomicFilterGroupType) => boolean
    }
}

export type taxonomicEventMatchLogicType = MakeLogicType<
    taxonomicEventMatchLogicValues,
    taxonomicEventMatchLogicActions,
    TaxonomicFilterLogicProps,
    taxonomicEventMatchLogicMeta
>

// A picker that excludes an event from its list must not offer or name it either.
function withoutExcluded(events: EventMatchApi[], taxonomicGroups: TaxonomicFilterGroup[]): EventMatchApi[] {
    const excluded =
        taxonomicGroups.find((group) => group.type === TaxonomicFilterGroupType.Events)?.excludedProperties ?? []
    return events.filter((event) => !excluded.includes(event.name)).slice(0, MAX_SUGGESTIONS)
}

/**
 * Asks the decision model which PostHog core events a search that matched no event name describes, for the
 * `taxonomic-filter-event-match` experiment. Mounted by the empty state of the events list and of the "All" list.
 * The test arm suggests the matched events, or says why there are none: the likely event was never sent, or the
 * search is only values. The control arm asks nothing and only reports that it reached the dead end.
 * Legacy surface only.
 */
export const taxonomicEventMatchLogic = kea<taxonomicEventMatchLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'taxonomicEventMatchLogic', key]),
    connect((props: TaxonomicFilterLogicProps) => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            projectLogic,
            ['currentProjectId'],
            taxonomicFilterLogic(props),
            ['activeTab', 'searchQuery', 'taxonomicGroupTypes', 'taxonomicGroups'],
        ],
        actions: [taxonomicFilterLogic(props), ['selectItem', 'setSearchQuery']],
    })),
    actions({
        findEventMatches: (searchQuery: string) => ({ searchQuery }),
        startEventMatch: (query: string) => ({ query }),
        setEventMatches: (eventMatches: EventMatches | null) => ({ eventMatches }),
        selectEventMatch: (match: EventMatchApi) => ({ match }),
    }),
    reducers({
        eventMatches: [
            null as EventMatches | null,
            {
                setEventMatches: (_, { eventMatches }) => eventMatches,
            },
        ],
        pendingQuery: [
            null as string | null,
            {
                startEventMatch: (_, { query }) => query,
                setEventMatches: () => null,
            },
        ],
    }),
    selectors({
        currentAnswer: [
            (s) => [s.eventMatches, s.searchQuery, s.currentProjectId],
            (
                eventMatches: EventMatches | null,
                searchQuery: string,
                currentProjectId: number | null
            ): EventMatches | null =>
                // An answer for an older search or another project stays hidden, so a suggestion never names the wrong one.
                eventMatches?.query === searchQuery.trim() && eventMatches.projectId === currentProjectId
                    ? eventMatches
                    : null,
        ],
        hint: [
            (s) => [s.currentAnswer, s.suggestedEvents, s.taxonomicGroups, s.taxonomicGroupTypes],
            (
                currentAnswer: EventMatches | null,
                suggestedEvents: EventMatchApi[],
                taxonomicGroups: TaxonomicFilterGroup[],
                taxonomicGroupTypes: TaxonomicFilterGroupType[]
            ): EventMatchHint | null => {
                if (!currentAnswer || suggestedEvents.length > 0) {
                    return null
                }
                if (currentAnswer.outcome === 'only_values') {
                    return offersProperties(taxonomicGroupTypes) ? { kind: 'value' } : null
                }
                if (currentAnswer.outcome === 'not_ingested') {
                    const events = withoutExcluded(currentAnswer.unsent, taxonomicGroups)
                    return events.length > 0 ? { kind: 'unsent', events } : null
                }
                return null
            },
        ],
        suggestedEvents: [
            (s) => [s.currentAnswer, s.taxonomicGroups],
            (currentAnswer: EventMatches | null, taxonomicGroups: TaxonomicFilterGroup[]): EventMatchApi[] =>
                currentAnswer ? withoutExcluded(currentAnswer.matches, taxonomicGroups) : [],
        ],
        isMatching: [
            (s) => [s.pendingQuery, s.searchQuery],
            (pendingQuery: string | null, searchQuery: string): boolean =>
                pendingQuery !== null && pendingQuery === searchQuery.trim(),
        ],
        tabShowsSuggestions: [
            (s) => [s.activeTab],
            (activeTab: TaxonomicFilterGroupType): boolean => TABS_WITH_SUGGESTIONS.includes(activeTab),
        ],
    }),
    listeners(({ actions, values }) => ({
        setSearchQuery: ({ searchQuery }) => {
            actions.findEventMatches(searchQuery)
        },
        findEventMatches: async ({ searchQuery }, breakpoint) => {
            const query = searchQuery.trim()
            const projectId = values.currentProjectId
            const variant = values.featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_EVENT_MATCH]
            if (
                query.length < MIN_QUERY_LENGTH ||
                query.length > MAX_QUERY_LENGTH ||
                projectId === null ||
                !EXPERIMENT_VARIANTS.includes(String(variant)) ||
                !values.tabShowsSuggestions ||
                !values.taxonomicGroupTypes.includes(TaxonomicFilterGroupType.Events)
            ) {
                return
            }
            // A 404 blocks only the model call. Both arms still count as exposed, so the arms stay comparable.
            const asksTheModel = variant === TEST_VARIANT && !unavailableProjectIds.has(projectId)
            const remembered = asksTheModel ? answeredMatches.get(matchKey(projectId, query)) : undefined
            if (remembered) {
                reportEligible(projectId, query, values.activeTab, String(variant))
                actions.setEventMatches({ projectId, query, ...remembered })
                reportSuggested(values.suggestedEvents, values.activeTab)
                reportHint(values.hint, values.activeTab)
                return
            }
            if (asksTheModel) {
                actions.startEventMatch(query)
            }
            await breakpoint(EVENT_MATCH_DEBOUNCE_MS)
            // A tab opened during the pause hides this list, so the ask is dropped before it costs a model call.
            if (!values.tabShowsSuggestions) {
                actions.setEventMatches(null)
                return
            }
            // Both arms count as exposed once a settled search reaches the dead end the model would answer.
            reportEligible(projectId, query, values.activeTab, String(variant))
            if (!asksTheModel) {
                return
            }

            let answer: EventMatchAnswer
            try {
                const response = await taxonomicSearchIntentMatchEventsCreate(String(projectId), { query })
                answer = { matches: response.matches, outcome: response.outcome, unsent: response.unsent ?? [] }
            } catch (error: any) {
                if (error?.status === 404) {
                    unavailableProjectIds.add(projectId)
                } else if (!UNREPORTED_FAILURE_STATUSES.includes(error?.status)) {
                    posthog.captureException(error, {
                        feature: 'taxonomic-event-match',
                        projectId,
                        status: error?.status,
                    })
                }
                breakpoint()
                actions.setEventMatches(null)
                return
            }
            breakpoint()
            // A tab opened while the model answered hides this list, so the answer is dropped and never counted as shown.
            if (!values.tabShowsSuggestions) {
                actions.setEventMatches(null)
                return
            }
            answeredMatches.set(matchKey(projectId, query), answer)
            actions.setEventMatches({ projectId, query, ...answer })
            reportSuggested(values.suggestedEvents, values.activeTab)
            reportHint(values.hint, values.activeTab)
        },
        selectEventMatch: ({ match }) => {
            const eventsGroup = values.taxonomicGroups.find((group) => group.type === TaxonomicFilterGroupType.Events)
            if (!eventsGroup) {
                return
            }
            const position = values.suggestedEvents.findIndex((suggested) => suggested.name === match.name)
            if (position === -1) {
                return
            }
            // pinned: analytics event name and properties, the flag's success metric reads them
            posthog.capture('taxonomic filter event match selected', {
                surface: legacyTaxonomicSurface(),
                tab: values.activeTab,
                eventName: match.name,
                position,
            })
            actions.selectItem(eventsGroup, match.name, { name: match.name }, { position })
        },
    })),
    afterMount(({ actions, values }) => {
        actions.findEventMatches(values.searchQuery)
    }),
])
