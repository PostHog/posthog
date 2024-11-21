import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { SessionRecordingPlayerTab } from '~/types'

import type { miniFiltersLogicType } from './miniFiltersLogicType'

export type SharedListMiniFilter = {
    tab: SessionRecordingPlayerTab
    key: string
    name: string
    tooltip?: string
    enabled?: boolean
}

const MiniFilters: SharedListMiniFilter[] = [
    {
        tab: SessionRecordingPlayerTab.EVENTS,
        key: 'events-posthog',
        name: 'PostHog',
        tooltip: 'Standard PostHog events like Pageviews, Autocapture etc.',
    },
    {
        tab: SessionRecordingPlayerTab.EVENTS,
        key: 'events-custom',
        name: 'Custom',
        tooltip: 'Custom events tracked by your app',
    },
    {
        tab: SessionRecordingPlayerTab.EVENTS,
        key: 'events-pageview',
        name: 'Pageview / Screen',
        tooltip: 'Pageview (or Screen for mobile) events',
    },
    {
        tab: SessionRecordingPlayerTab.EVENTS,
        key: 'events-autocapture',
        name: 'Autocapture',
        tooltip: 'Autocapture events such as clicks and inputs',
    },
    {
        tab: SessionRecordingPlayerTab.EVENTS,
        key: 'events-exceptions',
        name: 'Exceptions',
        tooltip: 'Exception events from PostHog or its Sentry integration',
    },
    {
        tab: SessionRecordingPlayerTab.CONSOLE,
        key: 'console-info',
        name: 'Info',
    },
    {
        tab: SessionRecordingPlayerTab.CONSOLE,
        key: 'console-warn',
        name: 'Warn',
    },
    {
        tab: SessionRecordingPlayerTab.CONSOLE,
        key: 'console-error',
        name: 'Error',
    },
    {
        tab: SessionRecordingPlayerTab.NETWORK,
        key: 'performance-fetch',
        name: 'Fetch/XHR',
        tooltip: 'Requests during the session to external resources like APIs via XHR or Fetch',
    },
    {
        tab: SessionRecordingPlayerTab.NETWORK,
        key: 'performance-document',
        name: 'Doc',
        tooltip: 'Page load information collected on a fresh browser page load, refresh, or page paint.',
    },
    {
        tab: SessionRecordingPlayerTab.NETWORK,
        key: 'performance-assets-js',
        name: 'JS',
        tooltip: 'Scripts loaded during the session.',
    },
    {
        tab: SessionRecordingPlayerTab.NETWORK,
        key: 'performance-assets-css',
        name: 'CSS',
        tooltip: 'CSS loaded during the session.',
    },
    {
        tab: SessionRecordingPlayerTab.NETWORK,
        key: 'performance-assets-img',
        name: 'Img',
        tooltip: 'Images loaded during the session.',
    },
    {
        tab: SessionRecordingPlayerTab.NETWORK,
        key: 'performance-other',
        name: 'Other',
        tooltip: 'Any other network requests that do not fall into the other categories',
    },
    {
        tab: SessionRecordingPlayerTab.DOCTOR,
        key: 'doctor',
        name: 'Doctor',
        tooltip:
            'Doctor events are special events that are automatically detected by PostHog to help diagnose issues in replay.',
    },
    // NOTE: The below filters use the `response_status` property which is currently experiemental
    // and as such doesn't show for many browsers: https://developer.mozilla.org/en-US/docs/Web/API/PerformanceResourceTiming/responseStatus
    // We should only add these in if the recording in question has those values (otherwiseit is a confusing experience for the user)

    // {
    //     tab: SessionRecordingPlayerTab.PERFORMANCE,
    //     key: 'performance-2xx',
    //     name: '2xx',
    //     tooltip:
    //         'Requests that returned a HTTP status code of 2xx. The request was successfully received, understood, and accepted.',
    // },
    // {
    //     tab: SessionRecordingPlayerTab.PERFORMANCE,
    //     key: 'performance-4xx',
    //     name: '4xx',
    //     tooltip:
    //         'Requests that returned a HTTP status code of 4xx. The request contains bad syntax or cannot be fulfilled.',
    // },
    // {
    //     tab: SessionRecordingPlayerTab.PERFORMANCE,
    //     key: 'performance-5xx',
    //     name: '5xx',
    //     tooltip:
    //         'Requests that returned a HTTP status code of 5xx. The server failed to fulfil an apparently valid request.',
    // },
]
export type MiniFilterKey = (typeof MiniFilters)[number]['key']

export const miniFiltersLogic = kea<miniFiltersLogicType>([
    path(['scenes', 'session-recordings', 'player', 'miniFiltersLogic']),
    actions({
        setShowOnlyMatching: (showOnlyMatching: boolean) => ({ showOnlyMatching }),
        setTab: (tab: SessionRecordingPlayerTab) => ({ tab }),
        setMiniFilter: (key: string, enabled: boolean) => ({ key, enabled }),
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

        tab: [
            SessionRecordingPlayerTab.ALL as SessionRecordingPlayerTab,
            { persist: true },
            {
                setTab: (_, { tab }) => tab,
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
        miniFiltersForTab: [
            (s) => [s.selectedMiniFilters],
            (selectedMiniFilters): ((tab: SessionRecordingPlayerTab) => SharedListMiniFilter[]) => {
                return (tab: SessionRecordingPlayerTab) => {
                    return MiniFilters.filter((filter) => filter.tab === tab).map((x) => ({
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

        miniFiltersForTabByKey: [
            (s) => [s.miniFiltersForTab],
            (miniFiltersForTab): ((tab: SessionRecordingPlayerTab) => { [key: string]: SharedListMiniFilter }) => {
                return (tab) => {
                    return miniFiltersForTab(tab).reduce((acc, filter) => {
                        acc[filter.key] = filter
                        return acc
                    }, {})
                }
            },
        ],
    }),
    listeners(({ values }) => ({
        setTab: ({ tab }) => {
            eventUsageLogic.actions.reportRecordingInspectorTabViewed(tab)
        },
        setMiniFilter: ({ key, enabled }) => {
            if (enabled) {
                eventUsageLogic.actions.reportRecordingInspectorMiniFilterViewed(values.tab, key)
            }
        },
    })),
])
