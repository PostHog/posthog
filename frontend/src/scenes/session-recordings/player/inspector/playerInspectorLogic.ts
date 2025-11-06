import FuseClass from 'fuse.js'
import { actions, connect, events, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import {
    EventType as RRWebEventType,
    customEvent,
    eventWithTime,
    fullSnapshotEvent,
    pluginEvent,
} from '@posthog/rrweb-types'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ceilMsToClosestSecond, eventToDescription, humanizeBytes, objectsEqual, toParams } from 'lib/utils'
import { getText } from 'scenes/comments/Comment'
import {
    InspectorListItemPerformance,
    performanceEventDataLogic,
} from 'scenes/session-recordings/apm/performanceEventDataLogic'
import {
    filterInspectorListItems,
    itemToMiniFilter,
} from 'scenes/session-recordings/player/inspector/inspectorListFiltering'
import { MiniFilterKey, miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import {
    MatchingEventsMatchType,
    convertUniversalFiltersToRecordingsQuery,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import {
    CommentType,
    MatchedRecordingEvent,
    PerformanceEvent,
    RRWebRecordingConsoleLogPayload,
    RecordingConsoleLogV2,
    RecordingEventType,
} from '~/types'

import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
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

export type RecordingComment = {
    id: string
    notebookShortId: string
    notebookTitle: string
    comment: string
    timeInRecording: number
}

const _filterableItemTypes = ['events', 'console', 'network', 'comment', 'doctor'] as const
const _itemTypes = [
    ..._filterableItemTypes,
    'performance',
    'offline-status',
    'browser-visibility',
    'inactivity',
    'inspector-summary',
    'app-state',
    'session-change',
] as const

export type InspectorListItemType = (typeof _itemTypes)[number]
export type FilterableInspectorListItemTypes = (typeof _filterableItemTypes)[number]

export type InspectorListItemBase = {
    timestamp: Dayjs
    timeInRecording: number
    search: string
    highlightColor?: 'danger' | 'warning' | 'primary' | 'info'
    windowId?: string
    windowNumber?: number | '?' | undefined
    type: InspectorListItemType
    key: string
}

export type InspectorListItemEvent = InspectorListItemBase & {
    type: 'events'
    data: RecordingEventType
}

export type InspectorListItemInactivity = InspectorListItemBase & {
    type: 'inactivity'
    durationMs: number
}

export type InspectorListItemNotebookComment = InspectorListItemBase & {
    type: 'comment'
    source: 'notebook'
    data: RecordingComment
}

export type InspectorListItemComment = InspectorListItemBase & {
    type: 'comment'
    source: 'comment'
    data: CommentType
}

export type InspectorListItemConsole = InspectorListItemBase & {
    type: 'console'
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

interface SessionChangePayload {
    nextSessionId?: string
    previousSessionId?: string
    changeReason?: { noSessionId: boolean; activityTimeout: boolean; sessionPastMaximumLength: boolean }
}

export type InspectorListSessionChange = InspectorListItemBase & {
    type: 'session-change'
    tag: '$session_starting' | '$session_ending'
    data: SessionChangePayload
}

export type InspectorListItemDoctor = InspectorListItemBase & {
    type: 'doctor'
    tag: string
    data?: Record<string, any>
    window_id?: string
}

export type InspectorListItemAppState = InspectorListItemBase & {
    type: 'app-state'
    action: string
    stateEvent?: Record<string, any>
    window_id?: string
}

export type InspectorListItemSummary = InspectorListItemBase & {
    type: 'inspector-summary'
    clickCount: number | null
    keypressCount: number | null
    errorCount: number | null
}

export type InspectorListItem =
    | InspectorListItemEvent
    | InspectorListItemConsole
    | InspectorListItemPerformance
    | InspectorListOfflineStatusChange
    | InspectorListItemDoctor
    | InspectorListBrowserVisibility
    | InspectorListItemComment
    | InspectorListItemNotebookComment
    | InspectorListItemSummary
    | InspectorListItemInactivity
    | InspectorListItemAppState
    | InspectorListSessionChange

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
    const snapshotTypeName = RRWebEventType[snapshot.type]
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
    thingWithTime:
        | eventWithTime
        | PerformanceEvent
        | RecordingConsoleLogV2
        | RecordingEventType
        | { timestamp: string }
        | { timestamp: number },
    start: Dayjs | null
): {
    timeInRecording: number
    timestamp: dayjs.Dayjs
} {
    const timestamp = dayjs(thingWithTime.timestamp)
    const timeInRecording = timestamp.valueOf() - (start?.valueOf() ?? 0)
    return { timestamp, timeInRecording }
}

function niceify(tag: string): string {
    return tag.replace(/\$/g, '').replace(/_/g, ' ')
}

function estimateSize(snapshot: unknown): number {
    return new Blob([JSON.stringify(snapshot || '')]).size
}

function getPayloadFor(customEvent: customEvent, tag: string): Record<string, any> {
    if (tag === '$posthog_config') {
        return (customEvent.data.payload as any)?.config as Record<string, any>
    }

    if (tag === '$session_options') {
        return {
            ...((customEvent.data.payload as any)?.sessionRecordingOptions as Record<string, any>),
            activePlugins: (customEvent.data.payload as any)?.activePlugins,
        }
    }

    return customEvent.data.payload as Record<string, any>
}

function notebookCommentTimestamp(
    timeInRecording: number,
    start: Dayjs | null
): {
    timeInRecording: number
    timestamp: dayjs.Dayjs | undefined
} {
    const timestamp = start?.add(timeInRecording, 'ms')
    return { timestamp, timeInRecording }
}

function commentTimestamp(
    commentTime: Dayjs,
    start: Dayjs | null
): {
    timeInRecording: number
    timestamp: dayjs.Dayjs | undefined
} {
    return { timestamp: commentTime, timeInRecording: commentTime.valueOf() - (start?.valueOf() ?? 0) }
}

export const playerInspectorLogic = kea<playerInspectorLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerInspectorLogic', key]),
    props({} as PlayerInspectorLogicProps),
    key((props: PlayerInspectorLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: PlayerInspectorLogicProps) => ({
        actions: [
            miniFiltersLogic,
            ['setMiniFilter', 'setSearchQuery'],
            sessionRecordingEventUsageLogic,
            ['reportRecordingInspectorItemExpanded'],
            sessionRecordingDataCoordinatorLogic(props),
            ['loadFullEventData', 'setTrackedWindow'],
            sessionRecordingPlayerLogic(props),
            ['seekToTime', 'setSkippingToMatchingEvent'],
        ],
        values: [
            miniFiltersLogic,
            ['showOnlyMatching', 'miniFiltersByKey', 'searchQuery', 'miniFiltersForTypeByKey', 'miniFilters'],
            sessionRecordingDataCoordinatorLogic(props),
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
                'sessionNotebookComments',
                'sessionComments',
                'sessionCommentsLoading',
                'windowIdForTimestamp',
                'sessionPlayerMetaData',
                'segments',
                'trackedWindow',
            ],
            sessionRecordingPlayerLogic(props),
            ['currentPlayerTime', 'skipToFirstMatchingEvent'],
            performanceEventDataLogic({ key: props.playerKey, sessionRecordingId: props.sessionRecordingId }),
            ['allPerformanceEvents'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions(() => ({
        setItemExpanded: (index: number, expanded: boolean) => ({ index, expanded }),
        setSyncScrollPaused: (paused: boolean) => ({ paused }),
    })),
    reducers(() => ({
        expandedItems: [
            [] as number[],
            {
                setItemExpanded: (items, { index, expanded }) => {
                    return expanded ? [...items, index] : items.filter((item) => item !== index)
                },
                setMiniFilter: () => [],
                setSearchQuery: () => [],
                setTrackedWindow: () => [],
            },
        ],

        syncScrollPaused: [
            false,
            {
                setSyncScrollPaused: (_, { paused }) => paused,
                setItemExpanded: () => true,
            },
        ],
    })),
    loaders(({ actions, values, props }) => ({
        matchingEvents: [
            [] as MatchedRecordingEvent[] | null,
            {
                loadMatchingEvents: async () => {
                    const matchingEventsMatchType = props.matchingEventsMatchType
                    const matchType = matchingEventsMatchType?.matchType
                    if (!matchingEventsMatchType || matchType === 'none' || matchType === 'name') {
                        return null
                    }

                    const skipToEarliestEvent = (matchingEvents: MatchedRecordingEvent[]): void => {
                        if (values.skipToFirstMatchingEvent && matchingEvents.length > 0) {
                            const earliestMatchingEvent = matchingEvents.reduce((previous, current) =>
                                previous.timestamp < current.timestamp ? previous : current
                            )
                            const { timeInRecording } = timeRelativeToStart(earliestMatchingEvent, values.start)
                            const seekTime = ceilMsToClosestSecond(timeInRecording) - 1000

                            // Only show the "skipping to matching event" overlay if we're actually skipping (> 1 second from start)
                            if (seekTime > 1000) {
                                actions.setSkippingToMatchingEvent(true)
                                setTimeout(() => {
                                    actions.setSkippingToMatchingEvent(false)
                                }, 1500)
                            }

                            actions.seekToTime(seekTime)
                        }
                    }

                    if (matchType === 'uuid') {
                        if (!matchingEventsMatchType?.matchedEvents) {
                            console.error('UUID matching events type must include its array of matched events')
                        }
                        skipToEarliestEvent(matchingEventsMatchType.matchedEvents)
                        return matchingEventsMatchType.matchedEvents
                    }

                    const filters = matchingEventsMatchType?.filters
                    if (!filters) {
                        throw new Error('Backend matching events type must include its filters')
                    }

                    const params: RecordingsQuery = {
                        ...convertUniversalFiltersToRecordingsQuery(filters),
                        session_ids: [props.sessionRecordingId],
                    }

                    const response = await api.recordings.getMatchingEvents(toParams(params))
                    skipToEarliestEvent(response.results)
                    return response.results
                },
            },
        ],
    })),
    selectors(({ props }) => ({
        allowMatchingEventsFilter: [
            (s) => [s.miniFilters],
            (miniFilters): boolean => {
                return (
                    miniFilters.some((mf) => mf.type === 'events' && mf.enabled) &&
                    props.matchingEventsMatchType?.matchType !== 'none'
                )
            },
        ],

        windowNumberForID: [
            (s) => [s.windowIds],
            (windowIds) => {
                // Pre-compute window ID to number mapping for O(1) lookups
                const windowIdToNumber = new Map<string, number | '?'>()
                windowIds.forEach((id, index) => {
                    windowIdToNumber.set(id, index + 1)
                })

                return (windowId: string | undefined): number | '?' | undefined => {
                    if (windowIds.length <= 1) {
                        return undefined
                    }
                    if (!windowId) {
                        return '?'
                    }
                    return windowIdToNumber.get(windowId) || '?'
                }
            },
        ],

        processedSnapshotData: [
            (s) => [s.start, s.sessionPlayerData, s.windowNumberForID],
            (
                start,
                sessionPlayerData,
                windowNumberForID
            ): {
                offlineStatusChanges: InspectorListOfflineStatusChange[]
                browserVisibilityChanges: InspectorListBrowserVisibility[]
                doctorEvents: InspectorListItemDoctor[]
                consoleItems: InspectorListItemConsole[]
                appStateItems: InspectorListItemAppState[]
                contextItems: InspectorListItem[]
                rawConsoleLogs: RecordingConsoleLogV2[]
            } => {
                const offlineStatusChanges: InspectorListOfflineStatusChange[] = []
                const browserVisibilityChanges: InspectorListBrowserVisibility[] = []
                const doctorEvents: InspectorListItemDoctor[] = []
                const consoleLogs: RecordingConsoleLogV2[] = []
                const consoleItems: InspectorListItemConsole[] = []
                const appStateItems: InspectorListItemAppState[] = []
                const snapshotCounts: Record<string, Record<string, number>> = {}
                const consoleLogSeenCache = new Set<string>()
                const sessionChangeItems: InspectorListSessionChange[] = []

                // Single pass through all snapshots
                Object.entries(sessionPlayerData.snapshotsByWindowId).forEach(([windowId, snapshots]) => {
                    if (!snapshotCounts[windowId]) {
                        snapshotCounts[windowId] = {}
                    }

                    ;(snapshots as eventWithTime[]).forEach((snapshot: eventWithTime) => {
                        // Track snapshot counts for doctor events
                        const description = snapshotDescription(snapshot)
                        snapshotCounts[windowId][description] = (snapshotCounts[windowId][description] || 0) + 1

                        // Process custom events (type 5)
                        if (_isCustomSnapshot(snapshot)) {
                            const customEvent = snapshot as customEvent
                            const tag = customEvent.data.tag
                            const { timestamp, timeInRecording } = timeRelativeToStart(snapshot, start || dayjs())

                            // Offline status changes
                            if (['browser offline', 'browser online'].includes(tag)) {
                                offlineStatusChanges.push({
                                    type: 'offline-status',
                                    offline: tag === 'browser offline',
                                    timestamp: timestamp,
                                    timeInRecording: timeInRecording,
                                    search: tag,
                                    windowId: windowId,
                                    windowNumber: windowNumberForID(windowId),
                                    highlightColor: 'warning',
                                    key: `${timestamp.valueOf()}-offline-status-${tag}`,
                                } satisfies InspectorListOfflineStatusChange)
                            }

                            if (['$session_ending', '$session_starting'].includes(tag)) {
                                const item: InspectorListSessionChange = {
                                    type: 'session-change',
                                    timestamp: timestamp,
                                    timeInRecording: timeInRecording,
                                    search: tag,
                                    tag: tag as '$session_starting' | '$session_ending',
                                    data: customEvent.data.payload as SessionChangePayload,
                                    windowId: windowId,
                                    windowNumber: windowNumberForID(windowId),
                                    key: `${timestamp.valueOf()}-session-change-${tag}`,
                                }
                                sessionChangeItems.push(item)
                            }

                            // Browser visibility changes
                            if (['window hidden', 'window visible'].includes(tag)) {
                                browserVisibilityChanges.push({
                                    type: 'browser-visibility',
                                    status: tag === 'window hidden' ? 'hidden' : 'visible',
                                    timestamp: timestamp,
                                    timeInRecording: timeInRecording,
                                    search: tag,
                                    windowId: windowId,
                                    windowNumber: windowNumberForID(windowId),
                                    highlightColor: 'warning',
                                    key: `${timestamp.valueOf()}-browser-visibility-${tag}`,
                                } satisfies InspectorListBrowserVisibility)
                            }

                            // App state items
                            if (tag === 'app-state') {
                                const payload = customEvent.data.payload as {
                                    title: string
                                    stateEvent: Record<string, any>
                                }
                                const actionTitle = payload?.title as string
                                const stateEvent = payload?.stateEvent as Record<string, any>
                                if (actionTitle && stateEvent) {
                                    appStateItems.push({
                                        type: 'app-state',
                                        timestamp,
                                        timeInRecording,
                                        action: actionTitle,
                                        search: actionTitle,
                                        window_id: windowId,
                                        windowId: windowId,
                                        windowNumber: windowNumberForID(windowId),
                                        stateEvent,
                                        key: `${timestamp.valueOf()}-app-state-${actionTitle}`,
                                    })
                                }
                            }

                            // Doctor events (other custom events)
                            if (
                                start &&
                                ![
                                    '$pageview',
                                    'window hidden',
                                    'browser offline',
                                    'browser online',
                                    'window visible',
                                    'app-state',
                                ].includes(tag)
                            ) {
                                doctorEvents.push({
                                    type: 'doctor',
                                    timestamp,
                                    timeInRecording,
                                    tag: niceify(tag),
                                    search: niceify(tag),
                                    window_id: windowId,
                                    windowId: windowId,
                                    windowNumber: windowNumberForID(windowId),
                                    data: getPayloadFor(customEvent, tag),
                                    key: `${timestamp.valueOf()}-doctor-${tag}`,
                                })
                            }
                        }

                        // Process full snapshot events
                        if (isFullSnapshotEvent(snapshot) && start) {
                            const { timestamp, timeInRecording } = timeRelativeToStart(snapshot, start)
                            doctorEvents.push({
                                type: 'doctor',
                                timestamp,
                                timeInRecording,
                                tag: 'full snapshot event',
                                search: 'full snapshot event',
                                window_id: windowId,
                                windowId: windowId,
                                windowNumber: windowNumberForID(windowId),
                                data: { snapshotSize: humanizeBytes(estimateSize(snapshot)) },
                                key: `${timestamp.valueOf()}-doctor-full-snapshot`,
                            })
                        }

                        // Process plugin snapshots (console logs)
                        if (_isPluginSnapshot(snapshot) && snapshot.data.plugin === CONSOLE_LOG_PLUGIN_NAME) {
                            const data = snapshot.data.payload as RRWebRecordingConsoleLogPayload
                            const { level, payload, trace } = data
                            const lines = (Array.isArray(payload) ? payload : [payload]).filter((x) => !!x) as string[]
                            const content = lines.join('\n')
                            const cacheKey = `${snapshot.timestamp}::${content}`

                            if (!consoleLogSeenCache.has(cacheKey)) {
                                consoleLogSeenCache.add(cacheKey)

                                const lastLogLine = consoleLogs[consoleLogs.length - 1]
                                if (lastLogLine?.content === content) {
                                    if (lastLogLine.count === undefined) {
                                        lastLogLine.count = 1
                                    } else {
                                        lastLogLine.count += 1
                                    }
                                } else {
                                    const consoleLog = {
                                        timestamp: snapshot.timestamp,
                                        windowId: windowId,
                                        windowNumber: windowNumberForID(windowId),
                                        content,
                                        lines,
                                        level,
                                        trace,
                                        count: 1,
                                    }
                                    consoleLogs.push(consoleLog)

                                    // Also create the inspector list item
                                    const { timestamp: itemTimestamp, timeInRecording } = timeRelativeToStart(
                                        consoleLog,
                                        start || dayjs()
                                    )
                                    consoleItems.push({
                                        type: 'console',
                                        timestamp: itemTimestamp,
                                        timeInRecording,
                                        search: content,
                                        data: consoleLog,
                                        highlightColor:
                                            level === 'error' ? 'danger' : level === 'warn' ? 'warning' : undefined,
                                        windowId: windowId,
                                        windowNumber: windowNumberForID(windowId),
                                        key: `${itemTimestamp.valueOf()}-console-${level}-${consoleLogs.length - 1}`,
                                    })
                                }
                            }
                        }
                    })
                })

                // Add the snapshot counts summary to doctor events
                if (start) {
                    doctorEvents.push({
                        type: 'doctor',
                        timestamp: start,
                        timeInRecording: 0,
                        tag: 'count of snapshot types by window',
                        search: 'count of snapshot types by window',
                        data: snapshotCounts,
                        key: `${start.valueOf()}-doctor-snapshot-counts`,
                    })
                }

                const contextItems: InspectorListItem[] = [
                    ...offlineStatusChanges,
                    ...browserVisibilityChanges,
                    ...doctorEvents,
                    ...sessionChangeItems,
                ]

                return {
                    offlineStatusChanges,
                    browserVisibilityChanges,
                    doctorEvents,
                    consoleItems,
                    appStateItems,
                    contextItems,
                    rawConsoleLogs: consoleLogs,
                }
            },
            { resultEqualityCheck: objectsEqual },
        ],

        notebookCommentItems: [
            (s) => [s.sessionNotebookComments, s.windowIdForTimestamp, s.windowNumberForID, s.start],
            (
                sessionNotebookComments,
                windowIdForTimestamp,
                windowNumberForID,
                start
            ): InspectorListItemNotebookComment[] => {
                const items: InspectorListItemNotebookComment[] = []
                for (const comment of sessionNotebookComments || []) {
                    const { timestamp, timeInRecording } = notebookCommentTimestamp(comment.timeInRecording, start)
                    if (timestamp) {
                        items.push({
                            highlightColor: 'primary',
                            type: 'comment',
                            source: 'notebook',
                            timeInRecording: timeInRecording,
                            timestamp: timestamp,
                            search: comment.comment,
                            data: comment,
                            windowId: windowIdForTimestamp(timestamp.valueOf()),
                            windowNumber: windowNumberForID(windowIdForTimestamp(timestamp.valueOf())),
                            key: `notebook-comment-${comment.id}`,
                        })
                    }
                }
                return items
            },
            { resultEqualityCheck: objectsEqual },
        ],

        commentItems: [
            (s) => [s.sessionComments, s.windowIdForTimestamp, s.windowNumberForID, s.start],
            (sessionComments, windowIdForTimestamp, windowNumberForID, start): InspectorListItemComment[] => {
                const items: InspectorListItemComment[] = []
                for (const comment of sessionComments || []) {
                    if (!comment.item_context?.time_in_recording) {
                        continue
                    }

                    const { timestamp, timeInRecording } = commentTimestamp(
                        dayjs(comment.item_context.time_in_recording),
                        start
                    )
                    if (timestamp) {
                        const item: InspectorListItemComment = {
                            timestamp,
                            timeInRecording,
                            type: 'comment',
                            source: 'comment',
                            highlightColor: 'primary',
                            windowId: windowIdForTimestamp(timestamp.valueOf()),
                            windowNumber: windowNumberForID(windowIdForTimestamp(timestamp.valueOf())),
                            data: comment,
                            search: getText(comment),
                            key: `comment-${comment.id}`,
                        }
                        items.push(item)
                    }
                }
                return items
            },
            { resultEqualityCheck: objectsEqual },
        ],

        allContextItems: [
            (s) => [s.start, s.processedSnapshotData, s.windowNumberForID, s.sessionPlayerMetaData, s.segments],
            (start, processedSnapshotData, windowNumberForID, sessionPlayerMetaData, segments) => {
                const items: InspectorListItem[] = []

                segments
                    .filter((segment) => segment.kind === 'gap')
                    .filter((segment) => segment.durationMs > 15000)
                    .map((segment) => {
                        const { timestamp, timeInRecording } = timeRelativeToStart(
                            { timestamp: segment.startTimestamp },
                            start
                        )
                        items.push({
                            type: 'inactivity',
                            durationMs: segment.durationMs,
                            windowId: segment.windowId,
                            windowNumber: windowNumberForID(segment.windowId),
                            timestamp,
                            timeInRecording,
                            search: 'inactiv',
                            key: `inactivity-${segment.startTimestamp}`,
                        })
                    })

                // Add all pre-processed context items at once
                items.push(...(processedSnapshotData?.contextItems || []))

                // now we've calculated everything else,
                // we always start with a context row
                // that lets us show a little summary
                if (start) {
                    items.push({
                        type: 'inspector-summary',
                        timestamp: start,
                        timeInRecording: 0,
                        search: '',
                        clickCount: sessionPlayerMetaData?.click_count || null,
                        keypressCount: sessionPlayerMetaData?.keypress_count || null,
                        errorCount: 0,
                        key: `inspector-summary-${start.valueOf()}`,
                    })
                }

                // NOTE: Native JS sorting is relatively slow here - be careful changing this
                items.sort((a, b) => (a.timestamp.valueOf() > b.timestamp.valueOf() ? 1 : -1))

                return items
            },
            { resultEqualityCheck: objectsEqual },
        ],

        allItems: [
            (s) => [
                s.start,
                s.allPerformanceEvents,
                s.processedSnapshotData,
                s.sessionEventsData,
                s.matchingEvents,
                s.windowNumberForID,
                s.allContextItems,
                s.commentItems,
                s.notebookCommentItems,
                s.sessionPlayerData,
                s.miniFiltersByKey,
            ],
            (
                start,
                performanceEvents,
                processedSnapshotData,
                eventsData,
                matchingEvents,
                windowNumberForID,
                allContextItems,
                commentItems,
                notebookCommentItems,
                sessionPlayerData,
                miniFiltersByKey
            ): {
                items: InspectorListItem[]
                itemsByMiniFilterKey: Record<MiniFilterKey, InspectorListItem[]>
                itemsByType: Record<FilterableInspectorListItemTypes | 'context', InspectorListItem[]>
            } => {
                // Pre-compute categorizations during item creation
                const items: InspectorListItem[] = []
                const itemsByMiniFilterKey: Record<MiniFilterKey, InspectorListItem[]> = {
                    'events-posthog': [],
                    'events-custom': [],
                    'events-pageview': [],
                    'events-autocapture': [],
                    'events-exceptions': [],
                    'console-info': [],
                    'console-warn': [],
                    'console-error': [],
                    'console-app-state': [],
                    'performance-fetch': [],
                    'performance-document': [],
                    'performance-assets-js': [],
                    'performance-assets-css': [],
                    'performance-assets-img': [],
                    'performance-other': [],
                    comment: [],
                    doctor: [],
                }
                const itemsByType: Record<FilterableInspectorListItemTypes | 'context', InspectorListItem[]> = {
                    ['events']: [],
                    ['console']: [],
                    ['network']: [],
                    ['doctor']: [],
                    ['comment']: [],
                    context: [],
                }
                let summaryItem: InspectorListItemSummary | undefined

                // Helper function to add item and categorize it
                const addItem = (item: InspectorListItem): void => {
                    items.push(item)

                    // Categorize by mini-filter
                    const miniFilter = itemToMiniFilter(item, miniFiltersByKey)
                    if (miniFilter) {
                        itemsByMiniFilterKey[miniFilter.key].push(item)
                    }

                    // Categorize by type
                    const itemType = ['events', 'console', 'network', 'doctor', 'comment'].includes(
                        item.type as FilterableInspectorListItemTypes
                    )
                        ? (item.type as FilterableInspectorListItemTypes | 'context')
                        : 'context'
                    itemsByType[itemType].push(item)
                }

                // PERFORMANCE EVENTS
                const performanceEventsArr = performanceEvents || []
                for (const event of performanceEventsArr) {
                    const responseStatus = event.response_status || null

                    if (event.entry_type === 'paint') {
                        // We don't include paint events as they are covered in the navigation events
                        continue
                    }

                    const { timestamp, timeInRecording } = timeRelativeToStart(event, start)
                    addItem({
                        type: 'network',
                        timestamp,
                        timeInRecording,
                        search: event.name || '',
                        data: event,
                        highlightColor: (responseStatus || 0) >= 400 ? 'danger' : undefined,
                        windowId: event.window_id,
                        windowNumber: windowNumberForID(event.window_id),
                        key: `performance-${event.uuid}`,
                    })
                }

                // CONSOLE LOGS (already processed)
                for (const consoleItem of processedSnapshotData?.consoleItems || []) {
                    addItem(consoleItem)
                }

                let errorCount = 0
                for (const event of eventsData || []) {
                    let isMatchingEvent = false

                    if (event.event === '$exception') {
                        errorCount += 1
                    }

                    if (matchingEvents?.length) {
                        isMatchingEvent = !!matchingEvents.find(
                            (x: MatchedRecordingEvent) => x.uuid === String(event.id)
                        )
                    } else if (props.matchingEventsMatchType?.matchType === 'name') {
                        isMatchingEvent = props.matchingEventsMatchType?.eventNames?.includes(event.event)
                    }

                    const search = `${
                        getCoreFilterDefinition(event.event, TaxonomicFilterGroupType.Events)?.label ??
                        event.event ??
                        ''
                    } ${eventToDescription(event)}`.replace(/['"]+/g, '')

                    const { timestamp, timeInRecording } = timeRelativeToStart(event, start)
                    addItem({
                        type: 'events',
                        timestamp,
                        timeInRecording,
                        search: search,
                        data: {
                            ...event,
                            distinct_id: sessionPlayerData.person?.distinct_ids?.[0] || event.distinct_id,
                        },
                        highlightColor: isMatchingEvent
                            ? 'primary'
                            : event.event === '$exception'
                              ? 'danger'
                              : event.event === '$user_feedback_recording_started' ||
                                  event.event === '$user_feedback_recording_stopped'
                                ? 'info'
                                : undefined,
                        windowId: event.properties?.$window_id,
                        windowNumber: windowNumberForID(event.properties?.$window_id),
                        key: `event-${event.id}`,
                    })
                }

                for (const event of allContextItems || []) {
                    if (event.type === 'inspector-summary') {
                        summaryItem = event as InspectorListItemSummary
                        summaryItem.errorCount = errorCount
                    } else {
                        addItem(event)
                    }
                }

                for (const comment of commentItems || []) {
                    addItem(comment)
                }

                for (const notebookComment of notebookCommentItems || []) {
                    addItem(notebookComment)
                }

                for (const stateLogItem of processedSnapshotData?.appStateItems || []) {
                    addItem(stateLogItem)
                }

                // NOTE: Native JS sorting is relatively slow here - be careful changing this
                items.sort((a, b) => (a.timestamp.valueOf() > b.timestamp.valueOf() ? 1 : -1))

                // Add summary item at the beginning if it exists
                if (summaryItem) {
                    items.unshift(summaryItem)
                    if (items.length > 1) {
                        items[0].windowNumber = items[1]?.windowNumber
                        items[0].windowId = items[1]?.windowId
                    }
                }

                return {
                    items,
                    itemsByMiniFilterKey,
                    itemsByType,
                }
            },
            { resultEqualityCheck: objectsEqual },
        ],

        filteredItems: [
            (s) => [
                s.allItems,
                s.miniFiltersByKey,
                s.showOnlyMatching,
                s.allowMatchingEventsFilter,
                s.trackedWindow,
                s.hasEventsToDisplay,
            ],
            (
                allItemsData,
                miniFiltersByKey,
                showOnlyMatching,
                allowMatchingEventsFilter,
                trackedWindow,
                hasEventsToDisplay
            ): InspectorListItem[] => {
                const filteredItems = filterInspectorListItems({
                    allItems: allItemsData.items,
                    miniFiltersByKey,
                    allowMatchingEventsFilter,
                    showOnlyMatching,
                    trackedWindow,
                    hasEventsToDisplay,
                })

                // need to collapse adjacent inactivity items
                // they look wrong next to each other
                return filteredItems.reduce((acc, item, index) => {
                    if (item.type === 'inactivity') {
                        const previousItem = filteredItems[index - 1]
                        if (previousItem?.type === 'inactivity') {
                            previousItem.durationMs += item.durationMs
                            return acc
                        }
                    }
                    acc.push(item)
                    return acc
                }, [] as InspectorListItem[])
            },
            { resultEqualityCheck: objectsEqual },
        ],

        seekbarItems: [
            (s) => [
                s.allItems,
                s.miniFiltersByKey,
                s.showOnlyMatching,
                s.allowMatchingEventsFilter,
                s.trackedWindow,
                s.hasEventsToDisplay,
            ],
            (
                allItemsData,
                miniFiltersByKey,
                showOnlyMatching,
                allowMatchingEventsFilter,
                trackedWindow,
                hasEventsToDisplay
            ): (InspectorListItemEvent | InspectorListItemComment)[] => {
                // Pre-filter to only events and comments, avoiding the full filterInspectorListItems call
                const eventAndCommentItems: (InspectorListItemEvent | InspectorListItemComment)[] = []

                for (const item of allItemsData.items) {
                    // Only process events and comments
                    if (item.type !== 'events' && item.type !== 'comment') {
                        continue
                    }

                    // Skip events if there are no events to display
                    if (item.type === 'events' && !hasEventsToDisplay) {
                        continue
                    }

                    // Apply tracking window filter early
                    if (trackedWindow && item.windowId !== trackedWindow) {
                        continue
                    }

                    // Type assertion since we've already checked the type
                    const typedItem = item as InspectorListItemEvent | InspectorListItemComment

                    // Apply event-specific filters
                    if (item.type === 'events') {
                        // Skip if matching events filter is active and item doesn't match
                        if (allowMatchingEventsFilter && showOnlyMatching && item.highlightColor !== 'primary') {
                            continue
                        }

                        // Apply mini-filters for events using proper categorization
                        const eventFilter = itemToMiniFilter(item, miniFiltersByKey)
                        if (eventFilter && !eventFilter.enabled) {
                            continue
                        }
                    } else if (item.type === 'comment') {
                        // Apply mini-filters for comments
                        const commentFilter = miniFiltersByKey['comment']
                        if (commentFilter && !commentFilter.enabled) {
                            continue
                        }
                    }

                    eventAndCommentItems.push(typedItem)
                }

                // If we have too many items, apply priority filtering and sampling
                if (eventAndCommentItems.length > MAX_SEEKBAR_ITEMS) {
                    // First pass: keep only high-priority items
                    let priorityItems = eventAndCommentItems.filter((item) => {
                        const hasHighlightColor = !!item.highlightColor
                        const isPageView = item.type === 'events' && item.data.event === '$pageview'
                        const isFeedbackEvent =
                            item.type === 'events' &&
                            (item.data.event === '$user_feedback_recording_started' ||
                                item.data.event === '$user_feedback_recording_stopped')
                        const isComment = item.type === 'comment'
                        return hasHighlightColor || isPageView || isFeedbackEvent || isComment
                    })

                    // If still too many, sample them
                    if (priorityItems.length > MAX_SEEKBAR_ITEMS) {
                        const step = Math.ceil(priorityItems.length / MAX_SEEKBAR_ITEMS)
                        priorityItems = priorityItems.filter((_, i) => i % step === 0)
                    }

                    return priorityItems
                }

                return eventAndCommentItems
            },
            { resultEqualityCheck: objectsEqual },
        ],

        inspectorDataState: [
            (s) => [
                s.sessionEventsDataLoading,
                s.sessionPlayerMetaDataLoading,
                s.snapshotsLoading,
                s.sessionEventsData,
                s.processedSnapshotData,
                s.allPerformanceEvents,
                s.sessionComments,
                s.sessionCommentsLoading,
            ],
            (
                sessionEventsDataLoading: boolean,
                sessionPlayerMetaDataLoading: boolean,
                snapshotsLoading: boolean,
                events: RecordingEventType[] | null,
                processedSnapshotData: {
                    offlineStatusChanges: InspectorListOfflineStatusChange[]
                    browserVisibilityChanges: InspectorListBrowserVisibility[]
                    doctorEvents: InspectorListItemDoctor[]
                    consoleLogs: RecordingConsoleLogV2[]
                    appStateItems: InspectorListItemAppState[]
                } | null,
                performanceEvents: PerformanceEvent[] | null,
                sessionComments: CommentType[] | null,
                sessionCommentsLoading: boolean
            ): Record<FilterableInspectorListItemTypes, 'loading' | 'ready' | 'empty'> => {
                const dataForEventsState = sessionEventsDataLoading ? 'loading' : events?.length ? 'ready' : 'empty'
                const dataForConsoleState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !processedSnapshotData
                        ? 'loading'
                        : processedSnapshotData?.consoleLogs?.length
                          ? 'ready'
                          : 'empty'
                const dataForNetworkState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !performanceEvents
                        ? 'loading'
                        : performanceEvents.length
                          ? 'ready'
                          : 'empty'
                const dataForDoctorState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !processedSnapshotData
                        ? 'loading'
                        : processedSnapshotData?.doctorEvents?.length
                          ? 'ready'
                          : 'empty'

                // TODO include notebook comments here?
                const dataForCommentState = sessionCommentsLoading
                    ? 'loading'
                    : sessionComments?.length
                      ? 'ready'
                      : 'empty'

                return {
                    ['events']: dataForEventsState,
                    ['console']: dataForConsoleState,
                    ['network']: dataForNetworkState,
                    ['comment']: dataForCommentState,
                    ['doctor']: dataForDoctorState,
                }
            },
        ],

        isLoading: [
            (s) => [s.inspectorDataState],
            (inspectorDataState): boolean => Object.values(inspectorDataState).some((state) => state === 'loading'),
        ],

        isReady: [
            (s) => [s.inspectorDataState],
            (inspectorDataState): boolean => Object.values(inspectorDataState).every((state) => state === 'ready'),
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
                return fuse.search(searchQuery).map((x) => x.item)
            },
            { resultEqualityCheck: objectsEqual },
        ],

        allItemsList: [(s) => [s.allItems], (allItemsData): InspectorListItem[] => allItemsData.items],

        /**
         * All items by mini-filter key, not filtered items, so that we can count the unfiltered sets
         */
        allItemsByMiniFilterKey: [
            (s) => [s.allItems],
            (allItemsData): Record<MiniFilterKey, InspectorListItem[]> => allItemsData.itemsByMiniFilterKey,
        ],

        /**
         * All items by item type, not filtered items, so that we can count the unfiltered sets
         */
        allItemsByItemType: [
            (s) => [s.allItems],
            (allItemsData): Record<FilterableInspectorListItemTypes | 'context', InspectorListItem[]> =>
                allItemsData.itemsByType,
        ],

        hasEventsToDisplay: [
            (s) => [s.allItemsByItemType],
            (allItemsByItemType): boolean => allItemsByItemType['events']?.length > 0,
        ],
    })),
    listeners(({ values, actions }) => ({
        setItemExpanded: ({ index, expanded }) => {
            if (expanded) {
                const item = values.items[index]
                actions.reportRecordingInspectorItemExpanded(item.type, index)

                if (item.type === 'events') {
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
