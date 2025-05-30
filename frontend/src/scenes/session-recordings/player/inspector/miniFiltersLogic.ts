import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { FilterableInspectorListItemTypes } from '~/types'

import type { miniFiltersLogicType } from './miniFiltersLogicType'

export type SharedListMiniFilter = {
    type: FilterableInspectorListItemTypes
    key: string
    name: string
    tooltip?: string
    enabled?: boolean
}

const MiniFilters: SharedListMiniFilter[] = [
    {
        type: FilterableInspectorListItemTypes.EVENTS,
        key: 'events-posthog',
        name: 'PostHog',
        tooltip: 'Standard PostHog events except Pageviews, Autocapture, and Exceptions.',
    },
    {
        type: FilterableInspectorListItemTypes.EVENTS,
        key: 'events-custom',
        name: 'Custom',
        tooltip: 'Custom events tracked by your app',
    },
    {
        type: FilterableInspectorListItemTypes.EVENTS,
        key: 'events-pageview',
        name: 'Pageview / Screen',
        tooltip: 'Pageview (or Screen for mobile) events',
    },
    {
        type: FilterableInspectorListItemTypes.EVENTS,
        key: 'events-autocapture',
        name: 'Autocapture',
        tooltip: 'Autocapture events such as clicks and inputs',
    },
    {
        type: FilterableInspectorListItemTypes.EVENTS,
        key: 'events-exceptions',
        name: 'Exceptions',
        tooltip: 'Exception events from PostHog or its Sentry integration',
    },
    {
        type: FilterableInspectorListItemTypes.CONSOLE,
        key: 'console-info',
        name: 'Info',
    },
    {
        type: FilterableInspectorListItemTypes.CONSOLE,
        key: 'console-warn',
        name: 'Warn',
    },
    {
        type: FilterableInspectorListItemTypes.CONSOLE,
        key: 'console-error',
        name: 'Error',
    },
    {
        type: FilterableInspectorListItemTypes.NETWORK,
        key: 'performance-fetch',
        name: 'Fetch/XHR',
        tooltip: 'Requests during the session to external resources like APIs via XHR or Fetch',
    },
    {
        type: FilterableInspectorListItemTypes.NETWORK,
        key: 'performance-document',
        name: 'Doc',
        tooltip: 'Page load information collected on a fresh browser page load, refresh, or page paint.',
    },
    {
        type: FilterableInspectorListItemTypes.NETWORK,
        key: 'performance-assets-js',
        name: 'JS',
        tooltip: 'Scripts loaded during the session.',
    },
    {
        type: FilterableInspectorListItemTypes.NETWORK,
        key: 'performance-assets-css',
        name: 'CSS',
        tooltip: 'CSS loaded during the session.',
    },
    {
        type: FilterableInspectorListItemTypes.NETWORK,
        key: 'performance-assets-img',
        name: 'Img',
        tooltip: 'Images loaded during the session.',
    },
    {
        type: FilterableInspectorListItemTypes.NETWORK,
        key: 'performance-other',
        name: 'Other',
        tooltip: 'Any other network requests that do not fall into the other categories',
    },
    {
        type: FilterableInspectorListItemTypes.DOCTOR,
        key: 'doctor',
        name: 'Doctor',
        tooltip:
            'Doctor events are special events that are automatically detected by PostHog to help diagnose issues in replay.',
    },
]
export type MiniFilterKey = (typeof MiniFilters)[number]['key']

const defaulMinifilters = [
    'events-posthog',
    'events-custom',
    'events-pageview',
    'events-autocapture',
    'events-exceptions',
    'console-info',
    'console-warn',
    'console-error',
]

export const miniFiltersLogic = kea<miniFiltersLogicType>([
    path(['scenes', 'session-recordings', 'player', 'miniFiltersLogic']),
    actions({
        setShowOnlyMatching: (showOnlyMatching: boolean) => ({ showOnlyMatching }),
        setMiniFilter: (key: MiniFilterKey, enabled: boolean) => ({ key, enabled }),
        setMiniFilters: (keys: MiniFilterKey[], enabled: boolean) => ({ keys, enabled }),
        setSearchQuery: (search: string) => ({ search }),
        resetMiniFilters: true,
    }),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingInspectorMiniFilterViewed']],
    })),
    reducers(() => ({
        showOnlyMatching: [
            false,
            { persist: true },
            {
                setShowOnlyMatching: (_, { showOnlyMatching }) => showOnlyMatching,
            },
        ],

        selectedMiniFilters: [
            defaulMinifilters,
            { persist: true },
            {
                setMiniFilter: (state, { key, enabled }) => {
                    const stateWithoutKey = state.filter((x) => x !== key)
                    if (enabled) {
                        // ensure it's in the array
                        // remove it if it's there and then add it back
                        return stateWithoutKey.concat(key)
                    }
                    // ensure it's not in the array
                    return stateWithoutKey
                },
                setMiniFilters: (state, { keys, enabled }) => {
                    const stateWithoutKeys = state.filter((x) => !keys.includes(x))
                    if (enabled) {
                        return stateWithoutKeys.concat(...keys)
                    }
                    return stateWithoutKeys
                },
                resetMiniFilters: () => defaulMinifilters,
            },
        ],

        searchQuery: [
            '',
            {
                setSearchQuery: (_, { search }) => search || '',
            },
        ],
    })),

    selectors({
        miniFiltersForType: [
            (s) => [s.selectedMiniFilters],
            (selectedMiniFilters): ((tab: FilterableInspectorListItemTypes) => SharedListMiniFilter[]) => {
                return (tab: FilterableInspectorListItemTypes) => {
                    return MiniFilters.filter((filter) => filter.type === tab).map((x) => ({
                        ...x,
                        enabled: selectedMiniFilters.includes(x.key),
                    }))
                }
            },
        ],

        hasEventsFiltersSelected: [
            (s) => [s.miniFiltersForType],
            (miniFiltersForType) => miniFiltersForType(FilterableInspectorListItemTypes.EVENTS).some((x) => x.enabled),
        ],

        miniFilters: [
            (s) => [s.selectedMiniFilters],
            (selectedMiniFilters): SharedListMiniFilter[] => {
                return MiniFilters.map((x) => ({
                    ...x,
                    enabled: selectedMiniFilters.includes(x.key),
                }))
            },
        ],

        miniFiltersByKey: [
            (s) => [s.miniFilters],
            (miniFilters): { [key: string]: SharedListMiniFilter } => {
                return miniFilters.reduce((acc, filter) => {
                    acc[filter.key] = filter
                    return acc
                }, {})
            },
        ],

        miniFiltersForTypeByKey: [
            (s) => [s.miniFiltersForType],
            (
                miniFiltersForType
            ): ((tab: FilterableInspectorListItemTypes) => { [key: string]: SharedListMiniFilter }) => {
                return (tab) => {
                    return miniFiltersForType(tab).reduce((acc, filter) => {
                        acc[filter.key] = filter
                        return acc
                    }, {})
                }
            },
        ],
    }),
    listeners(({ actions }) => ({
        setMiniFilter: ({ key, enabled }) => {
            if (enabled) {
                actions.reportRecordingInspectorMiniFilterViewed(key, enabled)
            }
        },
    })),
    events(({ values, actions }) => ({
        afterMount: () => {
            // we removed the `all` filters, if someone has them persisted we need to reset to default
            if (values.selectedMiniFilters.some((filter) => filter.includes('all'))) {
                actions.resetMiniFilters()
            }
        },
    })),
])
