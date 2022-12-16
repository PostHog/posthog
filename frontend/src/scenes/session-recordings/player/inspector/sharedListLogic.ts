import { actions, kea, reducers, path, listeners, connect, props, key, selectors } from 'kea'
import {
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
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
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

export type SharedListFilter = {
    key: string
    name: string
    enabled: boolean
}

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
            ['peformanceEvents', 'consoleLogs', 'sessionPlayerMetaData', 'sessionEventsData'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [playerSettingsLogic, ['setShowOnlyMatching']],
    })),
    actions(() => ({
        setTab: (tab: SessionRecordingPlayerTab) => ({ tab }),
        setWindowIdFilter: (windowId: WindowOption) => ({ windowId }),
        setSearchQuery: (search: string) => ({ search }),
        setItemExpanded: (index: number, expanded: boolean) => ({ index, expanded }),
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

                setTab: (_, {}) => [],
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

    selectors(() => ({
        miniFilters: [
            (s) => [s.tab],
            (tab): SharedListFilter[] => {
                let filters: SharedListFilter[] = []

                if (tab === SessionRecordingPlayerTab.ALL) {
                    filters = filters.concat([
                        {
                            key: 'all-automatic',
                            name: 'Auto',
                            enabled: true,
                        },
                        {
                            key: 'all-errors',
                            name: 'Errors',
                            enabled: false,
                        },
                        {
                            key: 'all-verbose',
                            name: 'Verbose',
                            enabled: false,
                        },
                        {
                            key: 'all-everything',
                            name: 'Everything',
                            enabled: false,
                        },
                    ])
                }

                if (tab === SessionRecordingPlayerTab.EVENTS) {
                    filters = filters.concat([
                        {
                            key: 'events-all',
                            name: 'All',
                            enabled: true,
                        },
                        {
                            key: 'events-posthog',
                            name: 'PostHog',
                            enabled: false,
                        },
                        {
                            key: 'events-custom',
                            name: 'Custom',
                            enabled: false,
                        },
                        {
                            key: 'events-actions',
                            name: 'Pageview / Screen',
                            enabled: false,
                        },
                        {
                            key: 'events-autocapture',
                            name: 'Autocapture',
                            enabled: false,
                        },
                    ])
                }

                if (tab === SessionRecordingPlayerTab.CONSOLE) {
                    filters = filters.concat([
                        {
                            key: 'console-all',
                            name: 'All',
                            enabled: true,
                        },
                        {
                            key: 'console-info',
                            name: 'Info',
                            enabled: false,
                        },
                        {
                            key: 'console-log',
                            name: 'Log',
                            enabled: false,
                        },
                        {
                            key: 'console-warn',
                            name: 'Warn',
                            enabled: false,
                        },
                        {
                            key: 'console-error',
                            name: 'Error',
                            enabled: false,
                        },
                    ])
                }

                if (tab === SessionRecordingPlayerTab.PERFORMANCE) {
                    filters = filters.concat([
                        {
                            key: 'performance-all',
                            name: 'All',
                            enabled: true,
                        },
                        {
                            key: 'performance-xhr',
                            name: 'XHR / Fetch',
                            enabled: false,
                        },
                        {
                            key: 'performance-assets',
                            name: 'Assets',
                            enabled: false,
                        },
                        {
                            key: 'performance-other',
                            name: 'Other',
                            enabled: false,
                        },
                    ])
                }

                return filters
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

        allItems: [
            (s) => [s.tab, s.recordingTimeInfo, s.peformanceEvents, s.consoleLogs, s.sessionEventsData],
            (tab, recordingTimeInfo, peformanceEvents, consoleLogs, eventsData): SharedListItem[] => {
                const items: SharedListItem[] = []

                const allView = tab === SessionRecordingPlayerTab.ALL

                if (tab === SessionRecordingPlayerTab.ALL || tab === SessionRecordingPlayerTab.PERFORMANCE) {
                    for (const event of peformanceEvents || []) {
                        const timestamp = dayjs(event.timestamp)
                        if (allView && event.initiator_type !== 'fetch' && event.entry_type !== 'navigation') {
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
                        items.push({
                            type: SessionRecordingPlayerTab.CONSOLE,
                            timestamp,
                            timeInRecording: timestamp.diff(recordingTimeInfo.start, 'ms'),
                            search: event.rawString,
                            data: event,
                        })
                    }
                }

                if (tab === SessionRecordingPlayerTab.ALL || tab === SessionRecordingPlayerTab.EVENTS) {
                    for (const event of eventsData?.events || []) {
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
                        })
                    }
                }

                items.sort((a, b) => a.timestamp.diff(b.timestamp))

                return items
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
                    sortFn: (a, b) => allItems[a.idx].timestamp.diff(allItems[b.idx].timestamp) || a.score - b.score,
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
