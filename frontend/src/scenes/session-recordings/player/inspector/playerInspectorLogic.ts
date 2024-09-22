import { customEvent, EventType, eventWithTime, fullSnapshotEvent, pluginEvent } from '@rrweb/types'
import FuseClass from 'fuse.js'
import { actions, connect, events, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { getCoreFilterDefinition } from 'lib/taxonomy'
import { eventToDescription, objectsEqual, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    InspectorListItemPerformance,
    performanceEventDataLogic,
} from 'scenes/session-recordings/apm/performanceEventDataLogic'
import { filterInspectorListItems } from 'scenes/session-recordings/player/inspector/inspectorListFiltering'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    convertUniversalFiltersToRecordingsQuery,
    MatchingEventsMatchType,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import {
    MatchedRecordingEvent,
    PerformanceEvent,
    RecordingConsoleLogV2,
    RecordingEventType,
    RRWebRecordingConsoleLogPayload,
    SessionRecordingPlayerTab,
} from '~/types'

import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import type { playerInspectorLogicType } from './playerInspectorLogicType'

const CONSOLE_LOG_PLUGIN_NAME = 'rrweb/console@1'

const MAX_SEEKBAR_ITEMS = 100

export const IMAGE_WEB_EXTENSIONS = [
    'png',
    'jpg',
    'jpeg',
    'gif',
    'tif',
    'tiff',
    'gif',
    'svg',
    'webp',
    'bmp',
    'ico',
    'cur',
]

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<InspectorListItem> {}

export type InspectorListItemBase = {
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

export type RecordingComment = {
    id: string
    notebookShortId: string
    notebookTitle: string
    comment: string
    timeInRecording: number
}

export type InspectorListItemComment = InspectorListItemBase & {
    type: 'comment'
    data: RecordingComment
}

export type InspectorListItemConsole = InspectorListItemBase & {
    type: SessionRecordingPlayerTab.CONSOLE
    data: RecordingConsoleLogV2
}

export type InspectorListOfflineStatusChange = InspectorListItemBase & {
    type: 'offline-status'
    offline: boolean
}

export type InspectorListBrowserVisibility = InspectorListItemBase & {
    type: 'browser-visibility'
    status: 'hidden' | 'visible'
}

export type InspectorListItemDoctor = InspectorListItemBase & {
    type: SessionRecordingPlayerTab.DOCTOR
    tag: string
    data?: Record<string, any>
    window_id?: string
}

export type InspectorListItem =
    | InspectorListItemEvent
    | InspectorListItemConsole
    | InspectorListItemPerformance
    | InspectorListOfflineStatusChange
    | InspectorListItemDoctor
    | InspectorListBrowserVisibility
    | InspectorListItemComment

export interface PlayerInspectorLogicProps extends SessionRecordingPlayerLogicProps {
    matchingEventsMatchType?: MatchingEventsMatchType
}

function _isCustomSnapshot(x: unknown): x is customEvent {
    return (x as customEvent).type === 5
}

function _isPluginSnapshot(x: unknown): x is pluginEvent {
    return (x as pluginEvent).type === 6
}

function isFullSnapshotEvent(x: unknown): x is fullSnapshotEvent {
    return (x as fullSnapshotEvent).type === 2
}

function snapshotDescription(snapshot: eventWithTime): string {
    const snapshotTypeName = EventType[snapshot.type]
    let suffix = ''
    if (_isCustomSnapshot(snapshot)) {
        suffix = ': ' + (snapshot as customEvent).data.tag
    }
    if (_isPluginSnapshot(snapshot)) {
        suffix = ': ' + (snapshot as pluginEvent).data.plugin
    }
    return snapshotTypeName + suffix
}

function timeRelativeToStart(
    thingWithTime: eventWithTime | PerformanceEvent | RecordingConsoleLogV2 | RecordingEventType,
    start: Dayjs | null
): {
    timeInRecording: number
    timestamp: dayjs.Dayjs
} {
    const timestamp = dayjs(thingWithTime.timestamp)
    const timeInRecording = timestamp.valueOf() - (start?.valueOf() ?? 0)
    return { timestamp, timeInRecording }
}

function commentTimestamp(
    comment: RecordingComment,
    start: Dayjs | null
): {
    timeInRecording: number
    timestamp: dayjs.Dayjs | undefined
} {
    const timestamp = start?.add(comment.timeInRecording, 'ms')
    return { timestamp, timeInRecording: comment.timeInRecording }
}

export const playerInspectorLogic = kea<playerInspectorLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerInspectorLogic', key]),
    props({} as PlayerInspectorLogicProps),
    key((props: PlayerInspectorLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: PlayerInspectorLogicProps) => ({
        actions: [
            playerSettingsLogic,
            ['setTab', 'setMiniFilter', 'setSearchQuery'],
            eventUsageLogic,
            ['reportRecordingInspectorItemExpanded'],
            sessionRecordingDataLogic(props),
            ['loadFullEventData'],
        ],
        values: [
            playerSettingsLogic,
            ['showOnlyMatching', 'showSeekbarTicks', 'tab', 'miniFiltersByKey', 'searchQuery'],
            sessionRecordingDataLogic(props),
            [
                'sessionPlayerData',
                'sessionPlayerMetaDataLoading',
                'snapshotsLoading',
                'sessionEventsData',
                'sessionEventsDataLoading',
                'windowIds',
                'start',
                'end',
                'durationMs',
                'sessionComments',
                'windowIdForTimestamp',
            ],
            sessionRecordingPlayerLogic(props),
            ['currentPlayerTime'],
            performanceEventDataLogic({ key: props.playerKey, sessionRecordingId: props.sessionRecordingId }),
            ['allPerformanceEvents'],
        ],
    })),
    actions(() => ({
        setWindowIdFilter: (windowId: string | null) => ({ windowId }),
        setItemExpanded: (index: number, expanded: boolean) => ({ index, expanded }),
        setSyncScrollPaused: (paused: boolean) => ({ paused }),
    })),
    reducers(() => ({
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
                setSearchQuery: () => [],
                setWindowIdFilter: () => [],
            },
        ],

        syncScrollPaused: [
            false,
            {
                setTab: () => false,
                setSyncScrollPaused: (_, { paused }) => paused,
                setItemExpanded: () => true,
            },
        ],
    })),
    loaders(({ props }) => ({
        matchingEventUUIDs: [
            [] as MatchedRecordingEvent[] | null,
            {
                loadMatchingEvents: async () => {
                    const matchingEventsMatchType = props.matchingEventsMatchType
                    const matchType = matchingEventsMatchType?.matchType
                    if (!matchingEventsMatchType || matchType === 'none' || matchType === 'name') {
                        return null
                    }

                    if (matchType === 'uuid') {
                        if (!matchingEventsMatchType?.eventUUIDs) {
                            console.error('UUID matching events type must include its event ids')
                        }
                        return matchingEventsMatchType.eventUUIDs.map((x) => ({ uuid: x } as MatchedRecordingEvent))
                    }

                    const filters = matchingEventsMatchType?.filters
                    if (!filters) {
                        throw new Error('Backend matching events type must include its filters')
                    }
                    const params = toParams({
                        ...convertUniversalFiltersToRecordingsQuery(filters),
                        session_ids: [props.sessionRecordingId],
                    })
                    const response = await api.recordings.getMatchingEvents(params)
                    return response.results.map((x) => ({ uuid: x } as MatchedRecordingEvent))
                },
            },
        ],
    })),
    selectors(({ props }) => ({
        showMatchingEventsFilter: [
            (s) => [s.tab],
            (tab): boolean => {
                return tab === SessionRecordingPlayerTab.EVENTS && props.matchingEventsMatchType?.matchType !== 'none'
            },
        ],

        offlineStatusChanges: [
            (s) => [s.start, s.sessionPlayerData],
            (start, sessionPlayerData): InspectorListOfflineStatusChange[] => {
                const logs: InspectorListOfflineStatusChange[] = []

                Object.entries(sessionPlayerData.snapshotsByWindowId).forEach(([windowId, snapshots]) => {
                    snapshots.forEach((snapshot: eventWithTime) => {
                        if (
                            snapshot.type === 5 // RRWeb custom event type
                        ) {
                            const customEvent = snapshot as customEvent
                            const tag = customEvent.data.tag

                            if (['browser offline', 'browser online'].includes(tag)) {
                                const { timestamp, timeInRecording } = timeRelativeToStart(snapshot, start)
                                logs.push({
                                    type: 'offline-status',
                                    offline: tag === 'browser offline',
                                    timestamp: timestamp,
                                    timeInRecording: timeInRecording,
                                    search: tag,
                                    windowId: windowId,
                                    highlightColor: 'warning',
                                } satisfies InspectorListOfflineStatusChange)
                            }
                        }
                    })
                })

                return logs
            },
        ],

        browserVisibilityChanges: [
            (s) => [s.start, s.sessionPlayerData],
            (start, sessionPlayerData): InspectorListBrowserVisibility[] => {
                const logs: InspectorListBrowserVisibility[] = []

                Object.entries(sessionPlayerData.snapshotsByWindowId).forEach(([windowId, snapshots]) => {
                    snapshots.forEach((snapshot: eventWithTime) => {
                        if (
                            snapshot.type === 5 // RRWeb custom event type
                        ) {
                            const customEvent = snapshot as customEvent
                            const tag = customEvent.data.tag

                            if (['window hidden', 'window visible'].includes(tag)) {
                                const { timestamp, timeInRecording } = timeRelativeToStart(snapshot, start)
                                logs.push({
                                    type: 'browser-visibility',
                                    status: tag === 'window hidden' ? 'hidden' : 'visible',
                                    timestamp: timestamp,
                                    timeInRecording: timeInRecording,
                                    search: tag,
                                    windowId: windowId,
                                    highlightColor: 'warning',
                                } satisfies InspectorListBrowserVisibility)
                            }
                        }
                    })
                })

                return logs
            },
        ],

        doctorEvents: [
            (s) => [s.start, s.sessionPlayerData],
            (start, sessionPlayerData): InspectorListItemDoctor[] => {
                if (!start) {
                    return []
                }

                const items: InspectorListItemDoctor[] = []

                const snapshotCounts: Record<string, Record<string, number>> = {}

                Object.entries(sessionPlayerData.snapshotsByWindowId).forEach(([windowId, snapshots]) => {
                    if (!snapshotCounts[windowId]) {
                        snapshotCounts[windowId] = {}
                    }

                    snapshots.forEach((snapshot: eventWithTime) => {
                        const description = snapshotDescription(snapshot)
                        snapshotCounts[windowId][description] = (snapshotCounts[windowId][description] || 0) + 1

                        if (_isCustomSnapshot(snapshot)) {
                            const customEvent = snapshot as customEvent
                            const tag = customEvent.data.tag

                            if (['$pageview', 'window hidden', 'browser offline', 'browser online'].includes(tag)) {
                                return
                            }

                            const { timestamp, timeInRecording } = timeRelativeToStart(snapshot, start)

                            items.push({
                                type: SessionRecordingPlayerTab.DOCTOR,
                                timestamp,
                                timeInRecording,
                                tag,
                                search: tag,
                                window_id: windowId,
                                data: customEvent.data.payload as Record<string, any>,
                            })
                        }
                        if (isFullSnapshotEvent(snapshot)) {
                            const { timestamp, timeInRecording } = timeRelativeToStart(snapshot, start)

                            items.push({
                                type: SessionRecordingPlayerTab.DOCTOR,
                                timestamp,
                                timeInRecording,
                                tag: 'fullSnapshotEvent',
                                search: 'fullSnapshotEvent',
                                window_id: windowId,
                                data: {},
                            })
                        }
                    })
                })

                items.push({
                    type: SessionRecordingPlayerTab.DOCTOR,
                    timestamp: start,
                    timeInRecording: 0,
                    tag: 'count of snapshot types by window',
                    search: 'count of snapshot types by window',
                    data: snapshotCounts,
                })

                return items
            },
        ],

        consoleLogs: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData): RecordingConsoleLogV2[] => {
                const logs: RecordingConsoleLogV2[] = []
                const seenCache = new Set<string>()

                Object.entries(sessionPlayerData.snapshotsByWindowId).forEach(([windowId, snapshots]) => {
                    snapshots.forEach((snapshot: eventWithTime) => {
                        if (_isPluginSnapshot(snapshot) && snapshot.data.plugin === CONSOLE_LOG_PLUGIN_NAME) {
                            const data = snapshot.data.payload as RRWebRecordingConsoleLogPayload
                            const { level, payload, trace } = data
                            const lines = (Array.isArray(payload) ? payload : [payload]).filter((x) => !!x) as string[]
                            const content = lines.join('\n')
                            const cacheKey = `${snapshot.timestamp}::${content}`

                            if (seenCache.has(cacheKey)) {
                                return
                            }
                            seenCache.add(cacheKey)

                            const lastLogLine = logs[logs.length - 1]
                            if (lastLogLine?.content === content) {
                                if (lastLogLine.count === undefined) {
                                    lastLogLine.count = 1
                                } else {
                                    lastLogLine.count += 1
                                }
                                return
                            }

                            logs.push({
                                timestamp: snapshot.timestamp,
                                windowId: windowId,
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
                s.start,
                s.allPerformanceEvents,
                s.consoleLogs,
                s.sessionEventsData,
                s.matchingEventUUIDs,
                s.offlineStatusChanges,
                s.doctorEvents,
                s.browserVisibilityChanges,
                s.sessionComments,
                s.windowIdForTimestamp,
            ],
            (
                start,
                performanceEvents,
                consoleLogs,
                eventsData,
                matchingEventUUIDs,
                offlineStatusChanges,
                doctorEvents,
                browserVisibilityChanges,
                sessionComments,
                windowIdForTimestamp
            ): InspectorListItem[] => {
                // NOTE: Possible perf improvement here would be to have a selector to parse the items
                // and then do the filtering of what items are shown, elsewhere
                // ALSO: We could move the individual filtering logic into the MiniFilters themselves
                // WARNING: Be careful of dayjs functions - they can be slow due to the size of the loop.
                const items: InspectorListItem[] = []

                // no conversion needed for offlineStatusChanges, they're ready to roll
                for (const event of offlineStatusChanges || []) {
                    items.push(event)
                }

                // no conversion needed for browserVisibilityChanges, they're ready to roll
                for (const event of browserVisibilityChanges || []) {
                    items.push(event)
                }

                // no conversion needed for doctor events, they're ready to roll
                for (const event of doctorEvents || []) {
                    items.push(event)
                }

                // PERFORMANCE EVENTS
                const performanceEventsArr = performanceEvents || []
                for (const event of performanceEventsArr) {
                    // TODO should we be defaulting to 200 here :shrug:
                    const responseStatus = event.response_status || 200

                    if (event.entry_type === 'paint') {
                        // We don't include paint events as they are covered in the navigation events
                        continue
                    }

                    const { timestamp, timeInRecording } = timeRelativeToStart(event, start)
                    items.push({
                        type: SessionRecordingPlayerTab.NETWORK,
                        timestamp,
                        timeInRecording,
                        search: event.name || '',
                        data: event,
                        highlightColor: responseStatus >= 400 ? 'danger' : undefined,
                        windowId: event.window_id,
                    })
                }

                // CONSOLE LOGS
                for (const event of consoleLogs || []) {
                    const { timestamp, timeInRecording } = timeRelativeToStart(event, start)
                    items.push({
                        type: SessionRecordingPlayerTab.CONSOLE,
                        timestamp,
                        timeInRecording,
                        search: event.content,
                        data: event,
                        highlightColor:
                            event.level === 'error' ? 'danger' : event.level === 'warn' ? 'warning' : undefined,
                        windowId: event.windowId,
                    })
                }

                for (const event of eventsData || []) {
                    let isMatchingEvent = false

                    if (matchingEventUUIDs?.length) {
                        isMatchingEvent = !!matchingEventUUIDs.find((x) => x.uuid === String(event.id))
                    } else if (props.matchingEventsMatchType?.matchType === 'name') {
                        isMatchingEvent = props.matchingEventsMatchType?.eventNames?.includes(event.event)
                    }

                    const search = `${
                        getCoreFilterDefinition(event.event, TaxonomicFilterGroupType.Events)?.label ??
                        event.event ??
                        ''
                    } ${eventToDescription(event)}`.replace(/['"]+/g, '')

                    const { timestamp, timeInRecording } = timeRelativeToStart(event, start)
                    items.push({
                        type: SessionRecordingPlayerTab.EVENTS,
                        timestamp,
                        timeInRecording,
                        search: search,
                        data: event,
                        highlightColor: isMatchingEvent
                            ? 'primary'
                            : event.event === '$exception'
                            ? 'danger'
                            : undefined,
                        windowId: event.properties?.$window_id,
                    })
                }

                for (const comment of sessionComments || []) {
                    const { timestamp, timeInRecording } = commentTimestamp(comment, start)
                    if (timestamp) {
                        items.push({
                            highlightColor: 'primary',
                            type: 'comment',
                            timeInRecording: timeInRecording,
                            timestamp: timestamp,
                            search: comment.comment,
                            data: comment,
                            // TODO we'd have to figure out which is the active window at this timestamp
                            windowId: windowIdForTimestamp(timestamp),
                        })
                    }
                }

                // NOTE: Native JS sorting is relatively slow here - be careful changing this
                items.sort((a, b) => (a.timestamp.valueOf() > b.timestamp.valueOf() ? 1 : -1))

                return items
            },
        ],

        filteredItems: [
            (s) => [
                s.allItems,
                s.tab,
                s.miniFiltersByKey,
                s.showOnlyMatching,
                s.showMatchingEventsFilter,
                s.windowIdFilter,
            ],
            (
                allItems,
                tab,
                miniFiltersByKey,
                showOnlyMatching,
                showMatchingEventsFilter,
                windowIdFilter
            ): InspectorListItem[] => {
                return filterInspectorListItems({
                    allItems,
                    tab,
                    miniFiltersByKey,
                    showMatchingEventsFilter,
                    showOnlyMatching,
                    windowIdFilter,
                })
            },
        ],

        seekbarItems: [
            (s) => [s.allItems, s.showOnlyMatching, s.showSeekbarTicks, s.showMatchingEventsFilter],
            (
                allItems,
                showOnlyMatching,
                showSeekbarTicks,
                showMatchingEventsFilter
            ): (InspectorListItemEvent | InspectorListItemComment)[] => {
                let items: (InspectorListItemEvent | InspectorListItemComment)[] = allItems.filter(
                    (item): item is InspectorListItemEvent | InspectorListItemComment => {
                        if (item.type === SessionRecordingPlayerTab.EVENTS) {
                            if (!showSeekbarTicks && ['$pageview', '$screen'].includes(item.data.event)) {
                                return false
                            }

                            return !(showMatchingEventsFilter && showOnlyMatching && item.highlightColor !== 'primary')
                        }

                        if (item.type === 'comment') {
                            return !showMatchingEventsFilter
                        }

                        return false
                    }
                )

                if (items.length > MAX_SEEKBAR_ITEMS) {
                    items = items.filter((item) => {
                        const isPrimary = item.highlightColor === 'primary'
                        const isPageView =
                            item.type === SessionRecordingPlayerTab.EVENTS && item.data.event === '$pageview'
                        const isComment = item.type === 'comment'
                        return isPrimary || isPageView || isComment
                    })

                    items = items.filter((_, i) => {
                        return i % Math.ceil(items.length / MAX_SEEKBAR_ITEMS) === 0
                    })
                }

                return items
            },
        ],

        tabsState: [
            (s) => [
                s.sessionEventsDataLoading,
                s.sessionPlayerMetaDataLoading,
                s.snapshotsLoading,
                s.sessionEventsData,
                s.consoleLogs,
                s.allPerformanceEvents,
                s.doctorEvents,
            ],
            (
                sessionEventsDataLoading,
                sessionPlayerMetaDataLoading,
                snapshotsLoading,
                events,
                logs,
                performanceEvents,
                doctorEvents
            ): Record<SessionRecordingPlayerTab, 'loading' | 'ready' | 'empty'> => {
                const tabEventsState = sessionEventsDataLoading ? 'loading' : events?.length ? 'ready' : 'empty'
                const tabConsoleState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !logs
                        ? 'loading'
                        : logs.length
                        ? 'ready'
                        : 'empty'
                const tabNetworkState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !performanceEvents
                        ? 'loading'
                        : performanceEvents.length
                        ? 'ready'
                        : 'empty'
                const tabDoctorState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !performanceEvents
                        ? 'loading'
                        : doctorEvents.length
                        ? 'ready'
                        : 'empty'
                return {
                    [SessionRecordingPlayerTab.ALL]: [tabEventsState, tabConsoleState, tabNetworkState].every(
                        (x) => x === 'loading'
                    )
                        ? 'loading'
                        : 'ready',
                    [SessionRecordingPlayerTab.EVENTS]: tabEventsState,
                    [SessionRecordingPlayerTab.CONSOLE]: tabConsoleState,
                    [SessionRecordingPlayerTab.NETWORK]: tabNetworkState,
                    [SessionRecordingPlayerTab.DOCTOR]: tabDoctorState,
                }
            },
        ],

        playbackIndicatorIndex: [
            (s) => [s.currentPlayerTime, s.items],
            (playerTime, items): number => {
                // Returns the index of the event that the playback is closest to
                if (!playerTime) {
                    return 0
                }

                const timeSeconds = Math.floor(playerTime / 1000)
                return items.findIndex((x) => Math.floor(x.timeInRecording / 1000) >= timeSeconds)
            },
        ],

        playbackIndicatorIndexStop: [
            (s) => [s.playbackIndicatorIndex, s.items],
            (playbackIndicatorIndex, items): number => (items.length + playbackIndicatorIndex) % items.length,
        ],

        fuse: [
            (s) => [s.filteredItems],
            (filteredItems): Fuse =>
                new FuseClass<InspectorListItem>(filteredItems, {
                    threshold: 0.3,
                    keys: ['search'],
                    findAllMatches: true,
                    ignoreLocation: true,
                    shouldSort: false,
                    useExtendedSearch: true,
                }),
        ],

        items: [
            (s) => [s.filteredItems, s.fuse, s.searchQuery],
            (filteredItems, fuse, searchQuery): InspectorListItem[] => {
                if (searchQuery === '') {
                    return filteredItems
                }
                return fuse.search(searchQuery).map((x: any) => x.item)
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        setItemExpanded: ({ index, expanded }) => {
            if (expanded) {
                eventUsageLogic.actions.reportRecordingInspectorItemExpanded(values.tab, index)

                const item = values.items[index]

                if (item.type === SessionRecordingPlayerTab.EVENTS) {
                    actions.loadFullEventData(item.data)
                }
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadMatchingEvents()
        },
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!objectsEqual(props.matchingEventsMatchType, oldProps.matchingEventsMatchType)) {
            actions.loadMatchingEvents()
        }
    }),
])
