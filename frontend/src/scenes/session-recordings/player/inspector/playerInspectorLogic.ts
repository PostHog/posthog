import { actions, kea, reducers, path, listeners, connect, props, key, selectors } from 'kea'
import {
    MatchedRecordingEvent,
    PerformanceEvent,
    RecordingConsoleLogV2,
    RecordingEventType,
    RecordingSegment,
    RRWebRecordingConsoleLogPayload,
    SessionRecordingPlayerTab,
} from '~/types'
import type { playerInspectorLogicType } from './playerInspectorLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import FuseClass from 'fuse.js'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import { eventToDescription } from 'lib/utils'
import { eventWithTime } from 'rrweb/typings/types'
import { CONSOLE_LOG_PLUGIN_NAME } from './v1/consoleLogsUtils'
import { consoleLogsListLogic } from './v1/consoleLogsListLogic'

// Helping kea-typegen navigate the exported default class for Fuse
// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface Fuse extends FuseClass<InspectorListItem> {}

type InspectorListItemBase = {
    timestamp: Dayjs
    timeInRecording: number
    search: string
    highlightColor?: 'danger' | 'warning' | 'primary'
    windowId?: string
}

export type InspectorListItemEvent = InspectorListItemBase & {
    type: SessionRecordingPlayerTab.EVENTS
    data: RecordingEventType
}

export type InspectorListItemConsole = InspectorListItemBase & {
    type: SessionRecordingPlayerTab.CONSOLE
    data: RecordingConsoleLogV2
}

export type InspectorListItemPerformance = InspectorListItemBase & {
    type: SessionRecordingPlayerTab.PERFORMANCE
    data: PerformanceEvent
}

export type InspectorListItem = InspectorListItemEvent | InspectorListItemConsole | InspectorListItemPerformance

// Settings local to each recording
export const playerInspectorLogic = kea<playerInspectorLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerInspectorLogic', key]),
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
                'sessionPlayerData',
                'sessionPlayerMetaData',
                'sessionPlayerMetaDataLoading',
                'sessionEventsData',
                'sessionEventsDataLoading',
                'windowIds',
            ],
            sessionRecordingPlayerLogic(props),
            ['currentPlayerTime'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions(() => ({
        setWindowIdFilter: (windowId: string | null) => ({ windowId }),
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
            null as string | null,
            {
                setWindowIdFilter: (_, { windowId }) => windowId || null,
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

        consoleLogs: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData): RecordingConsoleLogV2[] => {
                const logs: RecordingConsoleLogV2[] = []
                const seenCache = new Set<string>()

                sessionPlayerData.metadata.segments.forEach((segment: RecordingSegment) => {
                    sessionPlayerData.snapshotsByWindowId[segment.windowId]?.forEach((snapshot: eventWithTime) => {
                        if (
                            snapshot.type === 6 && // RRWeb plugin event type
                            snapshot.data.plugin === CONSOLE_LOG_PLUGIN_NAME
                        ) {
                            const data = snapshot.data.payload as RRWebRecordingConsoleLogPayload
                            const { level, payload, trace } = data
                            const lines = (Array.isArray(payload) ? payload : [payload]).filter((x) => !!x) as string[]
                            const content = lines.join('\n')
                            const cacheKey = `${snapshot.timestamp}::${content}`

                            if (seenCache.has(cacheKey)) {
                                return
                            }
                            seenCache.add(cacheKey)

                            if (logs[logs.length - 1]?.content === content) {
                                logs[logs.length - 1].count += 1
                                return
                            }

                            logs.push({
                                timestamp: snapshot.timestamp,
                                windowId: segment.windowId,
                                content,
                                lines,
                                level,
                                trace,
                                count: 1,
                            })
                        }
                    })
                })

                return logs
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
                s.windowIdFilter,
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
                showOnlyMatching,
                windowIdFilter
            ): InspectorListItem[] => {
                const items: InspectorListItem[] = []

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

                        if (windowIdFilter && event.window_id !== windowIdFilter) {
                            include = false
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
                            windowId: event.window_id,
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

                        if (windowIdFilter && event.windowId !== windowIdFilter) {
                            include = false
                        }

                        if (!include) {
                            continue
                        }

                        items.push({
                            type: SessionRecordingPlayerTab.CONSOLE,
                            timestamp,
                            timeInRecording: timestamp.diff(recordingTimeInfo.start, 'ms'),
                            search: event.content,
                            data: event,
                            highlightColor:
                                event.level === 'error' ? 'danger' : event.level === 'warn' ? 'warning' : undefined,
                            windowId: event.windowId,
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

                        if (windowIdFilter && event.properties?.$window_id !== windowIdFilter) {
                            include = false
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
                            windowId: event.properties?.$window_id,
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
            (allItems): Fuse =>
                new FuseClass<InspectorListItem>(allItems, {
                    threshold: 0.3,
                    keys: ['search'],
                    findAllMatches: true,
                    ignoreLocation: true,
                    shouldSort: false,
                }),
        ],

        items: [
            (s) => [s.allItems, s.fuse, s.searchQuery],
            (allItems, fuse, searchQuery): InspectorListItem[] => {
                if (searchQuery === '') {
                    return allItems
                }
                const items = fuse.search(searchQuery).map((x: any) => x.item)

                return items
            },
        ],
    })),
])
