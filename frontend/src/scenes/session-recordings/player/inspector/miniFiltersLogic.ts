import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { InspectorListItemType } from '~/types'

import type { miniFiltersLogicType } from './miniFiltersLogicType'

export type SharedListMiniFilter = {
    type: InspectorListItemType
    key: string
    name: string
    tooltip?: string
    enabled?: boolean
}

const MiniFilters: SharedListMiniFilter[] = [
    {
        type: InspectorListItemType.EVENTS,
        key: 'events-posthog',
        name: 'PostHog',
        tooltip: 'Standard PostHog events except Pageviews, Autocapture, and Exceptions.',
    },
    {
        type: InspectorListItemType.EVENTS,
        key: 'events-custom',
        name: 'Custom',
        tooltip: 'Custom events tracked by your app',
    },
    {
        type: InspectorListItemType.EVENTS,
        key: 'events-pageview',
        name: 'Pageview / Screen',
        tooltip: 'Pageview (or Screen for mobile) events',
    },
    {
        type: InspectorListItemType.EVENTS,
        key: 'events-autocapture',
        name: 'Autocapture',
        tooltip: 'Autocapture events such as clicks and inputs',
    },
    {
        type: InspectorListItemType.EVENTS,
        key: 'events-exceptions',
        name: 'Exceptions',
        tooltip: 'Exception events from PostHog or its Sentry integration',
    },
    {
        type: InspectorListItemType.CONSOLE,
        key: 'console-info',
        name: 'Info',
    },
    {
        type: InspectorListItemType.CONSOLE,
        key: 'console-warn',
        name: 'Warn',
    },
    {
        type: InspectorListItemType.CONSOLE,
        key: 'console-error',
        name: 'Error',
    },
    {
        type: InspectorListItemType.NETWORK,
        key: 'performance-fetch',
        name: 'Fetch/XHR',
        tooltip: 'Requests during the session to external resources like APIs via XHR or Fetch',
    },
    {
        type: InspectorListItemType.NETWORK,
        key: 'performance-document',
        name: 'Doc',
        tooltip: 'Page load information collected on a fresh browser page load, refresh, or page paint.',
    },
    {
        type: InspectorListItemType.NETWORK,
        key: 'performance-assets-js',
        name: 'JS',
        tooltip: 'Scripts loaded during the session.',
    },
    {
        type: InspectorListItemType.NETWORK,
        key: 'performance-assets-css',
        name: 'CSS',
        tooltip: 'CSS loaded during the session.',
    },
    {
        type: InspectorListItemType.NETWORK,
        key: 'performance-assets-img',
        name: 'Img',
        tooltip: 'Images loaded during the session.',
    },
    {
        type: InspectorListItemType.NETWORK,
        key: 'performance-other',
        name: 'Other',
        tooltip: 'Any other network requests that do not fall into the other categories',
    },
    {
        type: InspectorListItemType.DOCTOR,
        key: 'doctor',
        name: 'Doctor',
        tooltip:
            'Doctor events are special events that are automatically detected by PostHog to help diagnose issues in replay.',
    },
]
export type MiniFilterKey = (typeof MiniFilters)[number]['key']

export const miniFiltersLogic = kea<miniFiltersLogicType>([
    path(['scenes', 'session-recordings', 'player', 'miniFiltersLogic']),
    actions({
        setShowOnlyMatching: (showOnlyMatching: boolean) => ({ showOnlyMatching }),
        setMiniFilter: (key: MiniFilterKey, enabled: boolean) => ({ key, enabled }),
        setSearchQuery: (search: string) => ({ search }),
    }),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    reducers(() => ({
        showOnlyMatching: [
            false,
            { persist: true },
            {
                setShowOnlyMatching: (_, { showOnlyMatching }) => showOnlyMatching,
            },
        ],

        selectedMiniFilters: [
            [
                'events-posthog',
                'events-custom',
                'events-pageview',
                'events-autocapture',
                'events-exceptions',
                'console-info',
                'console-warn',
                'console-error',
            ] as MiniFilterKey[],
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
            (selectedMiniFilters): ((tab: InspectorListItemType) => SharedListMiniFilter[]) => {
                return (tab: InspectorListItemType) => {
                    return MiniFilters.filter((filter) => filter.type === tab).map((x) => ({
                        ...x,
                        enabled: selectedMiniFilters.includes(x.key),
                    }))
                }
            },
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
            (miniFiltersForType): ((tab: InspectorListItemType) => { [key: string]: SharedListMiniFilter }) => {
                return (tab) => {
                    return miniFiltersForType(tab).reduce((acc, filter) => {
                        acc[filter.key] = filter
                        return acc
                    }, {})
                }
            },
        ],
    }),
    listeners(() => ({
        setMiniFilter: ({ key, enabled }) => {
            if (enabled) {
                eventUsageLogic.actions.reportRecordingInspectorMiniFilterViewed(key, enabled)
            }
        },
    })),
])
