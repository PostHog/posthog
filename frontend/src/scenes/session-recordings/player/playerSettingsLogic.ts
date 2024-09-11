import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AutoplayDirection, SessionRecordingPlayerTab, SessionRecordingSidebarStacking } from '~/types'

import type { playerSettingsLogicType } from './playerSettingsLogicType'

export type SharedListMiniFilter = {
    tab: SessionRecordingPlayerTab
    key: string
    name: string
    // If alone, then enabling it will disable all the others
    alone?: boolean
    tooltip?: string
    enabled?: boolean
}

export enum TimestampFormat {
    Relative = 'relative',
    UTC = 'utc',
    Device = 'device',
}

export enum PlaybackViewMode {
    Recording = 'recording',
    Waterfall = 'waterfall',
}

const MiniFilters: SharedListMiniFilter[] = [
    {
        tab: SessionRecordingPlayerTab.ALL,
        key: 'all-automatic',
        name: 'Auto',
        alone: true,
        tooltip: 'Curated list of key PostHog events, custom events, error logs etc.',
    },
    {
        tab: SessionRecordingPlayerTab.ALL,
        key: 'all-errors',
        name: 'Errors',
        alone: true,
        tooltip: 'Events containing "error" or "exception" in their name and console errors',
    },
    {
        tab: SessionRecordingPlayerTab.ALL,
        key: 'all-everything',
        name: 'Everything',
        alone: true,
        tooltip: 'Everything that happened in this session',
    },
    {
        tab: SessionRecordingPlayerTab.EVENTS,
        key: 'events-all',
        name: 'All',
        alone: true,
        tooltip: 'All events tracked during this session',
    },
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
        key: 'console-all',
        name: 'All',
        alone: true,
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
        key: 'performance-all',
        name: 'All',
        alone: true,
        tooltip: 'All network performance information collected during the session',
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

// This logic contains player settings that should persist across players
// If key is not specified, it is global so it does not reset when recordings change in the main recordings page
export const playerSettingsLogic = kea<playerSettingsLogicType>([
    path(['scenes', 'session-recordings', 'player', 'playerSettingsLogic']),
    actions({
        setSkipInactivitySetting: (skipInactivitySetting: boolean) => ({ skipInactivitySetting }),
        setSpeed: (speed: number) => ({ speed }),
        setShowOnlyMatching: (showOnlyMatching: boolean) => ({ showOnlyMatching }),
        setHideViewedRecordings: (hideViewedRecordings: boolean) => ({ hideViewedRecordings }),
        setAutoplayDirection: (autoplayDirection: AutoplayDirection) => ({ autoplayDirection }),
        setTab: (tab: SessionRecordingPlayerTab) => ({ tab }),
        setMiniFilter: (key: string, enabled: boolean) => ({ key, enabled }),
        setSearchQuery: (search: string) => ({ search }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        setQuickFilterProperties: (properties: string[]) => ({ properties }),
        setTimestampFormat: (format: TimestampFormat) => ({ format }),
        setPreferredSidebarStacking: (stacking: SessionRecordingSidebarStacking) => ({ stacking }),
        setPlaybackViewMode: (mode: PlaybackViewMode) => ({ mode }),
        setSidebarOpen: (open: boolean) => ({ open }),
        setShowMouseTail: (showMouseTail: boolean) => ({ showMouseTail }),
        setShowSeekbarTicks: (show: boolean) => ({ show }),
    }),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    reducers(({ values }) => ({
        showFilters: [true, { persist: true }, { setShowFilters: (_, { showFilters }) => showFilters }],
        sidebarOpen: [false, { persist: true }, { setSidebarOpen: (_, { open }) => open }],
        preferredSidebarStacking: [
            SessionRecordingSidebarStacking.Horizontal as SessionRecordingSidebarStacking,
            { persist: true },
            {
                setPreferredSidebarStacking: (_, { stacking }) => stacking,
            },
        ],
        playbackViewMode: [
            PlaybackViewMode.Recording as PlaybackViewMode,
            { persist: true },
            {
                setPlaybackViewMode: (_, { mode }) => mode,
            },
        ],
        quickFilterProperties: [
            [...(values.currentTeam?.person_display_name_properties || [])] as string[],
            {
                persist: true,
            },
            {
                setQuickFilterProperties: (_, { properties }) => properties,
            },
        ],
        speed: [
            1,
            { persist: true },
            {
                setSpeed: (_, { speed }) => speed,
            },
        ],
        timestampFormat: [
            TimestampFormat.Relative as TimestampFormat,
            { persist: true },
            {
                setTimestampFormat: (_, { format }) => format,
            },
        ],
        skipInactivitySetting: [
            true,
            { persist: true },
            {
                setSkipInactivitySetting: (_, { skipInactivitySetting }) => skipInactivitySetting,
            },
        ],
        showOnlyMatching: [
            false,
            { persist: true },
            {
                setShowOnlyMatching: (_, { showOnlyMatching }) => showOnlyMatching,
            },
        ],
        autoplayDirection: [
            'older' as AutoplayDirection,
            { persist: true },
            {
                setAutoplayDirection: (_, { autoplayDirection }) => autoplayDirection,
            },
        ],
        hideViewedRecordings: [
            false,
            { persist: true },
            {
                setHideViewedRecordings: (_, { hideViewedRecordings }) => hideViewedRecordings,
            },
        ],
        showMouseTail: [
            true,
            { persist: true },
            {
                setShowMouseTail: (_, { showMouseTail }) => showMouseTail,
            },
        ],
        showSeekbarTicks: [
            true,
            { persist: true },
            {
                setShowSeekbarTicks: (_, { show }) => show,
            },
        ],

        // Inspector
        tab: [
            SessionRecordingPlayerTab.ALL as SessionRecordingPlayerTab,
            { persist: true },
            {
                setTab: (_, { tab }) => tab,
            },
        ],

        selectedMiniFilters: [
            ['all-automatic', 'console-all', 'events-all', 'performance-all'] as string[],
            { persist: true },
            {
                setMiniFilter: (state, { key, enabled }) => {
                    const selectedFilter = MiniFilters.find((x) => x.key === key)

                    if (!selectedFilter) {
                        return state
                    }
                    const filtersInTab = MiniFilters.filter((x) => x.tab === selectedFilter.tab)

                    const newFilters = state.filter((existingSelected) => {
                        const filterInTab = filtersInTab.find((x) => x.key === existingSelected)
                        if (!filterInTab) {
                            return true
                        }

                        if (enabled) {
                            if (selectedFilter.alone) {
                                return false
                            }
                            return filterInTab.alone ? false : true
                        }

                        if (existingSelected !== key) {
                            return true
                        }
                        return false
                    })

                    if (enabled) {
                        newFilters.push(key)
                    } else {
                        // Ensure the first one is checked if no others
                        if (filtersInTab.every((x) => !newFilters.includes(x.key))) {
                            newFilters.push(filtersInTab[0].key)
                        }
                    }

                    return newFilters
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
        miniFilters: [
            (s) => [s.tab, s.selectedMiniFilters],
            (tab, selectedMiniFilters): SharedListMiniFilter[] => {
                return MiniFilters.filter((filter) => filter.tab === tab).map((x) => ({
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
