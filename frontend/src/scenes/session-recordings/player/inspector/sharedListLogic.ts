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

// Settings local to each recording
export const sharedListLogic = kea<sharedListLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sharedListLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        logic: [eventUsageLogic],
        actions: [playerSettingsLogic, ['setTab', 'setMiniFilter']],
        values: [
            playerSettingsLogic,
            ['showOnlyMatching', 'tab', 'miniFiltersByKey'],
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
        setWindowIdFilter: (windowId: WindowOption) => ({ windowId }),
        setSearchQuery: (search: string) => ({ search }),
        setItemExpanded: (index: number, expanded: boolean) => ({ index, expanded }),
        setSyncScroll: (syncScroll: boolean) => ({ syncScroll }),
    })),
    reducers(({}) => ({
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
