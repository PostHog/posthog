import { actions, kea, reducers, path, listeners, connect, props, key, selectors } from 'kea'
import {
    MatchedRecordingEvent,
    PerformanceEvent,
    PlayerPosition,
    RecordingConsoleLogBase,
    RecordingEventType,
    RecordingWindowFilter,
    SessionRecordingPlayerTab,
} from '~/types'
import type { sharedListLogicType } from './sharedListLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { consoleLogsListLogic } from 'scenes/session-recordings/player/inspector/consoleLogsListLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import Fuse from 'fuse.js'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import { eventToDescription } from 'lib/utils'

export type WindowOption = RecordingWindowFilter.All | PlayerPosition['windowId']

type SharedListItemBase = {
    timestamp: Dayjs
    timeInRecording: number
    search: string
    highlightColor?: 'danger' | 'warning' | 'primary'
}

export type SharedListItemEvent = SharedListItemBase & {
    type: SessionRecordingPlayerTab.EVENTS
    data: RecordingEventType
}

export type SharedListItemConsole = SharedListItemBase & {
    type: SessionRecordingPlayerTab.CONSOLE
    data: RecordingConsoleLogBase
}

export type SharedListItemPerformance = SharedListItemBase & {
    type: SessionRecordingPlayerTab.PERFORMANCE
    data: PerformanceEvent
}

export type SharedListItem = SharedListItemEvent | SharedListItemConsole | SharedListItemPerformance

export type SharedListMiniFilter = {
    tab: SessionRecordingPlayerTab
    key: string
    name: string
    // If alone, then enabling it will disable all the others
    alone?: boolean
    tooltip?: string
    enabled?: boolean
}

const MiniFilters: SharedListMiniFilter[] = [
    {
        tab: SessionRecordingPlayerTab.ALL,
        key: 'all-automatic',
        name: 'Auto',
        alone: true,
    },
    {
        tab: SessionRecordingPlayerTab.ALL,
        key: 'all-errors',
        name: 'Errors',
        alone: true,
    },
    {
        tab: SessionRecordingPlayerTab.ALL,
        key: 'all-everything',
        name: 'Everything',
        alone: true,
    },
    {
        tab: SessionRecordingPlayerTab.EVENTS,
        key: 'events-all',
        name: 'All',
        alone: true,
    },
    {
        tab: SessionRecordingPlayerTab.EVENTS,
        key: 'events-posthog',
        name: 'PostHog',
    },
    { tab: SessionRecordingPlayerTab.EVENTS, key: 'events-custom', name: 'Custom' },
    { tab: SessionRecordingPlayerTab.EVENTS, key: 'events-pageview', name: 'Pageview / Screen' },
    { tab: SessionRecordingPlayerTab.EVENTS, key: 'events-autocapture', name: 'Autocapture' },
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
        tab: SessionRecordingPlayerTab.PERFORMANCE,
        key: 'performance-all',
        name: 'All',
        alone: true,
    },
    {
        tab: SessionRecordingPlayerTab.PERFORMANCE,
        key: 'performance-document',
        name: 'Document',
    },
    {
        tab: SessionRecordingPlayerTab.PERFORMANCE,
        key: 'performance-fetch',
        name: 'XHR / Fetch',
    },
    {
        tab: SessionRecordingPlayerTab.PERFORMANCE,
        key: 'performance-assets',
        name: 'Assets',
    },
    {
        tab: SessionRecordingPlayerTab.PERFORMANCE,
        key: 'performance-other',
        name: 'Other',
    },
    {
        tab: SessionRecordingPlayerTab.PERFORMANCE,
        key: 'performance-paint',
        name: 'Paint',
    },
]

// Settings local to each recording
export const sharedListLogic = kea<sharedListLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sharedListLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        logic: [eventUsageLogic],
        values: [
            playerSettingsLogic,
            ['showOnlyMatching'],
            sessionRecordingDataLogic(props),
            [
                'performanceEvents',
                'performanceEventsLoading',
                'consoleLogs',
                'sessionPlayerMetaData',
                'sessionPlayerMetaDataLoading',
                'sessionEventsData',
                'sessionEventsDataLoading',
            ],
            sessionRecordingPlayerLogic(props),
            ['currentPlayerTime'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions(() => ({
        setTab: (tab: SessionRecordingPlayerTab) => ({ tab }),
        setWindowIdFilter: (windowId: WindowOption) => ({ windowId }),
        setSearchQuery: (search: string) => ({ search }),
        setItemExpanded: (index: number, expanded: boolean) => ({ index, expanded }),
        setTimestampMode: (mode: 'absolute' | 'relative') => ({ mode }),
        setMiniFilter: (key: string, enabled: boolean) => ({ key, enabled }),
        setSyncScroll: (syncScroll: boolean) => ({ syncScroll }),
    })),
    reducers(({ values }) => ({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { search }) => search || '',
            },
        ],
        windowIdFilter: [
            RecordingWindowFilter.All as WindowOption,
            {
                setWindowIdFilter: (_, { windowId }) => windowId ?? RecordingWindowFilter.All,
            },
        ],
        tab: [
            (values.featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_V2]
                ? SessionRecordingPlayerTab.ALL
                : SessionRecordingPlayerTab.EVENTS) as SessionRecordingPlayerTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
        expandedItems: [
            [] as number[],
            {
                setItemExpanded: (items, { index, expanded }) => {
                    return expanded ? [...items, index] : items.filter((item) => item !== index)
                },

                setTab: () => [],
                setMiniFilter: () => [],
            },
        ],
        timestampMode: [
            'relative' as 'absolute' | 'relative',
            {
                setTimestampMode: (_, { mode }) => mode,
            },
        ],

        selectedMiniFilters: [
            ['all-automatic', 'console-all', 'events-all', 'performance-all'] as string[],
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
                            } else {
                                return filterInTab.alone ? false : true
                            }
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

        syncScroll: [
            true,
            {
                setTab: () => true,
                setMiniFilter: () => true,
                setSyncScroll: (_, { syncScroll }) => syncScroll,
                setItemExpanded: () => false,
            },
        ],
    })),
    listeners(() => ({
        setTab: ({ tab }) => {
            if (tab === SessionRecordingPlayerTab.CONSOLE) {
                eventUsageLogic
                    .findMounted()
                    ?.actions?.reportRecordingConsoleViewed(
                        consoleLogsListLogic.findMounted()?.values?.consoleListData?.length ?? 0
                    )
            }
        },
    })),

    selectors(({}) => ({
        loading: [
            (s) => [s.sessionEventsDataLoading, s.performanceEventsLoading, s.sessionPlayerMetaDataLoading],
            (sessionEventsDataLoading, performanceEventsLoading, sessionPlayerMetaDataLoading) => {
                return {
                    [SessionRecordingPlayerTab.ALL]: false,
                    // sessionEventsDataLoading || performanceEventsLoading || (sessionPlayerMetaDataLoading),
                    [SessionRecordingPlayerTab.EVENTS]: sessionEventsDataLoading,
                    [SessionRecordingPlayerTab.CONSOLE]: sessionPlayerMetaDataLoading,
                    [SessionRecordingPlayerTab.PERFORMANCE]: performanceEventsLoading,
                }
            },
        ],

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

        recordingTimeInfo: [
            (s) => [s.sessionPlayerMetaData],
            (sessionPlayerMetaData): { start: Dayjs; end: Dayjs; duration: number } => {
                const { startTimeEpochMs } = sessionPlayerMetaData?.metadata?.segments[0] || {}
                const start = dayjs(startTimeEpochMs)
                const duration = sessionPlayerMetaData?.metadata?.recordingDurationMs || 0
                const end = start.add(duration, 'ms')
                return { start, end, duration }
            },
        ],

        matchingEvents: [
            () => [(_, props) => props.matching],
            (matchingEvents): MatchedRecordingEvent[] => {
                return matchingEvents?.map((x: any) => x.events).flat() ?? []
            },
        ],

        allItems: [
            (s) => [
                s.tab,
                s.recordingTimeInfo,
                s.performanceEvents,
                s.consoleLogs,
                s.sessionEventsData,
                s.featureFlags,
                s.miniFiltersByKey,
                s.matchingEvents,
                s.showOnlyMatching,
            ],
            (
                tab,
                recordingTimeInfo,
                performanceEvents,
                consoleLogs,
                eventsData,
                featureFlags,
                miniFiltersByKey,
                matchingEvents,
                showOnlyMatching
            ): SharedListItem[] => {
                const items: SharedListItem[] = []

                if (
                    !!featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE] &&
                    (tab === SessionRecordingPlayerTab.ALL || tab === SessionRecordingPlayerTab.PERFORMANCE)
                ) {
                    for (const event of performanceEvents || []) {
                        const timestamp = dayjs(event.timestamp)

                        let include = false

                        if (
                            miniFiltersByKey['performance-all']?.enabled ||
                            miniFiltersByKey['all-everything']?.enabled
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['performance-document']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            event.entry_type === 'navigation'
                        ) {
                            include = true
                        }
                        if (
                            miniFiltersByKey['performance-fetch']?.enabled &&
                            event.entry_type === 'resource' &&
                            ['fetch', 'xmlhttprequest'].includes(event.initiator_type || '')
                        ) {
                            include = true
                        }

                        if (
                            miniFiltersByKey['performance-assets']?.enabled &&
                            event.entry_type === 'resource' &&
                            ['img', 'script', 'css', 'link'].includes(event.initiator_type || '')
                        ) {
                            include = true
                        }

                        if (
                            miniFiltersByKey['performance-other']?.enabled &&
                            event.entry_type === 'resource' &&
                            ['other'].includes(event.initiator_type || '')
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['performance-paint']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            event.entry_type === 'paint'
                        ) {
                            include = true
                        }

                        if (!include) {
                            continue
                        }

                        items.push({
                            type: SessionRecordingPlayerTab.PERFORMANCE,
                            timestamp,
                            timeInRecording: timestamp.diff(recordingTimeInfo.start, 'ms'),
                            search: event.name || '',
                            data: event,
                        })
                    }
                }

                if (tab === SessionRecordingPlayerTab.ALL || tab === SessionRecordingPlayerTab.CONSOLE) {
                    for (const event of consoleLogs || []) {
                        const timestamp = dayjs(event.timestamp)

                        let include = false

                        if (miniFiltersByKey['console-all']?.enabled || miniFiltersByKey['all-everything']?.enabled) {
                            include = true
                        }
                        if (miniFiltersByKey['console-info']?.enabled && ['log', 'info'].includes(event.level)) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['console-warn']?.enabled || miniFiltersByKey['all-automatic']?.enabled) &&
                            event.level === 'warn'
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['console-error']?.enabled ||
                                miniFiltersByKey['all-errors']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            event.level === 'error'
                        ) {
                            include = true
                        }

                        if (!include) {
                            continue
                        }

                        items.push({
                            type: SessionRecordingPlayerTab.CONSOLE,
                            timestamp,
                            timeInRecording: timestamp.diff(recordingTimeInfo.start, 'ms'),
                            search: event.rawString,
                            data: event,
                            highlightColor:
                                event.level === 'error' ? 'danger' : event.level === 'warn' ? 'warning' : undefined,
                        })
                    }
                }

                if (tab === SessionRecordingPlayerTab.ALL || tab === SessionRecordingPlayerTab.EVENTS) {
                    for (const event of eventsData?.events || []) {
                        let include = false

                        if (miniFiltersByKey['events-all']?.enabled || miniFiltersByKey['all-everything']?.enabled) {
                            include = true
                        }
                        if (miniFiltersByKey['events-posthog']?.enabled && event.event.startsWith('$')) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['events-custom']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            !event.event.startsWith('$')
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['events-pageview']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            ['$pageview', 'screen'].includes(event.event)
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['events-autocapture']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            event.event === '$autocapture'
                        ) {
                            include = true
                        }

                        if (
                            miniFiltersByKey['all-errors']?.enabled &&
                            (event.event === '$exception' || event.event.toLowerCase().includes('error'))
                        ) {
                            include = true
                        }

                        const isMatchingEvent = !!matchingEvents.find((x) => x.uuid === String(event.id))

                        if (showOnlyMatching && tab === SessionRecordingPlayerTab.EVENTS) {
                            // Special case - overrides the others
                            include = include && isMatchingEvent
                        }

                        if (!include) {
                            continue
                        }

                        const timestamp = dayjs(event.timestamp)
                        const search = `${
                            getKeyMapping(event.event, 'event')?.label ?? event.event ?? ''
                        } ${eventToDescription(event)}`.replace(/['"]+/g, '')

                        items.push({
                            type: SessionRecordingPlayerTab.EVENTS,
                            timestamp,
                            timeInRecording: timestamp.diff(recordingTimeInfo.start, 'ms'),
                            search: search,
                            data: event,
                            highlightColor: isMatchingEvent ? 'primary' : undefined,
                        })
                    }
                }

                // NOTE: Native JS sorting is super slow here!

                items.sort((a, b) => (a.timestamp.isAfter(b.timestamp) ? 1 : -1))

                return items
            },
        ],

        playbackIndicatorIndex: [
            (s) => [s.currentPlayerTime, s.items],
            (playerTime, items): number => {
                // Return the indexes of all the events
                if (!playerTime) {
                    return 0
                }

                const timeSeconds = Math.floor(playerTime / 1000)
                const startIndex = items.findIndex((x) => Math.floor(x.timeInRecording / 1000) >= timeSeconds)

                return startIndex
            },
        ],

        lastItemTimestamp: [
            (s) => [s.allItems],
            (allItems): Dayjs | undefined => {
                if (allItems.length === 0) {
                    return undefined
                }
                let maxTimestamp = allItems[0].timestamp

                for (const item of allItems) {
                    if (item.timestamp.isAfter(maxTimestamp)) {
                        maxTimestamp = item.timestamp
                    }
                }

                return maxTimestamp
            },
        ],

        fuse: [
            (s) => [s.allItems],
            (allItems): Fuse<SharedListItem> =>
                new Fuse<SharedListItem>(allItems, {
                    threshold: 0.3,
                    keys: ['search'],
                    findAllMatches: true,
                    ignoreLocation: true,
                    shouldSort: false,
                }),
        ],

        items: [
            (s) => [s.allItems, s.fuse, s.searchQuery],
            (allItems, fuse, searchQuery): SharedListItem[] => {
                if (searchQuery === '') {
                    return allItems
                }
                const items = fuse.search(searchQuery).map((x: any) => x.item)

                return items
            },
        ],
    })),
])
