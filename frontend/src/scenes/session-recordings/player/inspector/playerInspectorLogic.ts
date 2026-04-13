import equal from 'fast-deep-equal'
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
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ceilMsToClosestSecond, eventToDescription, humanizeBytes, toParams } from 'lib/utils'
import { createFuse } from 'lib/utils/fuseSearch'
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

import { LogMessage, RecordingsQuery } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import {
    CommentType,
    FilterLogicalOperator,
    MatchedRecordingEvent,
    PerformanceEvent,
    PropertyFilterType,
    PropertyOperator,
    RecordingEventType,
} from '~/types'

import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import {
    DoctorDiagnostics,
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from '../sessionRecordingPlayerLogic'
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

const _filterableItemTypes = ['events', 'console', 'network', 'comment', 'doctor', 'logs'] as const
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
    highlightColor?: 'danger' | 'warning' | 'primary'
    windowId?: number
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
}

export type InspectorListItemAppState = InspectorListItemBase & {
    type: 'app-state'
    action: string
    stateEvent?: Record<string, any>
}

export type InspectorListItemSummary = InspectorListItemBase & {
    type: 'inspector-summary'
    clickCount: number | null
    keypressCount: number | null
    errorCount: number | null
}

export type InspectorListItemLog = InspectorListItemBase & {
    type: 'logs'
    data: LogMessage
    | InspectorListItemDoctor
    | InspectorListBrowserVisibility
    | InspectorListItemComment
    | InspectorListItemNotebookComment
    | InspectorListItemSummary
    | InspectorListItemInactivity
    | InspectorListItemAppState
    | InspectorListSessionChange
    | InspectorListItemLog
        const previousItem = acc[acc.length - 1]
        if (item.type === 'inactivity' && previousItem?.type === 'inactivity') {
            acc[acc.length - 1] = { ...previousItem, durationMs: previousItem.durationMs + item.durationMs }
            return acc
        }
        acc.push(item)
        return acc
    }, [] as InspectorListItem[])
}

export type DisplayGroup = { indices: number[] }

function canGroup(current: InspectorListItem, next: InspectorListItem): boolean {
    if (current.type !== next.type || current.highlightColor !== next.highlightColor) {
        return false
    }
    switch (current.type) {
        case 'events':
            return next.type === 'events' && current.data.event === next.data.event && current.search === next.search
        case 'console':
            return next.type === 'console' && current.data.content === next.data.content
        default:
            return false
    }
}

/** Groups adjacent identical events and console logs into display rows. */
export function computeDisplayGroups(items: InspectorListItem[], groupSimilar: boolean): DisplayGroup[] {
    const groups: DisplayGroup[] = []

    for (let i = 0; i < items.length; i++) {
        if (groupSimilar && groups.length > 0) {
            const lastGroup = groups[groups.length - 1]
            if (canGroup(items[lastGroup.indices[0]], items[i])) {
                lastGroup.indices.push(i)
                continue
            }
        }

        groups.push({ indices: [i] })
    }

    return groups
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
            ['loadFullEventData', 'setTrackedWindow', 'registerWindowId', 'loadEventsSuccess'],
            sessionRecordingPlayerLogic(props),
            ['seekToTime', 'setSkippingToMatchingEvent'],
        ],
        values: [
            miniFiltersLogic,
            [
                'showOnlyMatching',
                'groupRepeatedItems',
                'miniFiltersByKey',
                'searchQuery',
                'miniFiltersForTypeByKey',
                'miniFilters',
            ],
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
                'uuidToIndex',
            ],
            sessionRecordingPlayerLogic(props),
            ['currentPlayerTime', 'skipToFirstMatchingEvent', 'doctorDiagnostics'],
            performanceEventDataLogic({ key: props.playerKey, sessionRecordingId: props.sessionRecordingId }),
            ['allPerformanceEvents'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions(() => ({
        setItemExpanded: (index: number, expanded: boolean) => ({ index, expanded }),
        setSyncScrollPaused: (paused: boolean) => ({ paused }),
        setLogsHasMore: (hasMore: boolean) => ({ hasMore }),
        setLogsNextCursor: (cursor: string | undefined) => ({ cursor }),
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
        logsHasMore: [
            false,
            {
                setLogsHasMore: (_, { hasMore }) => hasMore,
            },
        ],
        logsNextCursor: [
            undefined as string | undefined,
            {
                setLogsNextCursor: (_, { cursor }) => cursor,
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
        logs: [
            [] as LogMessage[],
            {
                loadLogs: async () => {
                    if (!values.featureFlags[FEATURE_FLAGS.SESSION_REPLAY_BACKEND_LOGS]) {
                        return []
                    }

                    const sessionId = props.sessionRecordingId
                    if (!sessionId || !values.start || !values.end) {
                        return []
                    }

                    try {
                        const response = await api.logs.query({
                            query: {
                                dateRange: {
                                    date_from: values.start.toISOString(),
                                    date_to: values.end.toISOString(),
                                },
                                filterGroup: {
                                    type: FilterLogicalOperator.And,
                                    values: [
                                        {
                                            type: FilterLogicalOperator.And,
                                            values: [
                                                {
                                                    key: 'session_id',
                                                    value: sessionId,
                                                    operator: PropertyOperator.Exact,
                                                    type: PropertyFilterType.LogAttribute,
                                                },
                                            ],
                                        },
                                    ],
                                },
                                severityLevels: [],
                                serviceNames: [],
                                limit: 1000,
                            },
                        })
                        actions.setLogsHasMore(response.hasMore)
                        actions.setLogsNextCursor(response.nextCursor)
                        return response.results
                    } catch (error) {
                        console.error('Failed to load backend logs for session replay', error)
                        return []
                    }
                },
                loadMoreLogs: async () => {
                    const cursor = values.logsNextCursor
                    if (!cursor || !values.start || !values.end) {
                        return values.logs
                    }

                    try {
                        const response = await api.logs.query({
                            query: {
                                dateRange: {
                                    date_from: values.start.toISOString(),
                                    date_to: values.end.toISOString(),
                                },
                                filterGroup: {
                                    type: FilterLogicalOperator.And,
                                    values: [
                                        {
                                            type: FilterLogicalOperator.And,
                                            values: [
                                                {
                                                    key: 'session_id',
                                                    value: props.sessionRecordingId,
                                                    operator: PropertyOperator.Exact,
                                                    type: PropertyFilterType.LogAttribute,
                                                },
                                            ],
                                        },
                                    ],
                                },
                                severityLevels: [],
                                serviceNames: [],
                                limit: 1000,
                                after: cursor,
                            },
                        })
                        actions.setLogsHasMore(response.hasMore)
                        actions.setLogsNextCursor(response.nextCursor)
                        return [...values.logs, ...response.results]
                    } catch (error) {
                        console.error('Failed to load more backend logs for session replay', error)
                        return values.logs
                    }
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

                                const collapseConsole = !collapseInspectorItems
                                const lastLogLine = consoleLogs[consoleLogs.length - 1]
                                if (collapseConsole && lastLogLine?.content === content) {
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
            { resultEqualityCheck: equal },
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
            {
                resultEqualityCheck: equal,
            },
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
            { resultEqualityCheck: equal },
        ],

        runtimeDoctorEvents: [
            (s) => [s.start, s.doctorDiagnostics],
            (start: Dayjs | null, doctorDiagnostics: DoctorDiagnostics | null): InspectorListItemDoctor[] => {
                if (!start) {
                    return []
                }

                const items: InspectorListItemDoctor[] = []

                if (doctorDiagnostics && doctorDiagnostics.assetErrorTotal > 0) {
                    items.push({
                        type: 'doctor',
                        timestamp: start,
                        timeInRecording: 0,
                        tag: `asset errors (${doctorDiagnostics.assetErrorTotal} total)`,
                        search: `asset errors ${doctorDiagnostics.assetErrorTypeNames}`,
                        data: doctorDiagnostics.assetErrors,
                        highlightColor: 'warning',
                        key: 'doctor-asset-errors',
                    })
                }

                const warningCount = doctorDiagnostics?.rrwebWarningCount ?? 0
                if (doctorDiagnostics && warningCount > 0) {
                    const summary = doctorDiagnostics.rrwebWarningSummary ?? {}
                    items.push({
                        type: 'doctor',
                        timestamp: start,
                        timeInRecording: 0,
                        tag: `rrweb warnings (${warningCount})`,
                        search: 'rrweb warnings',
                        data: Object.keys(summary).length > 0 ? summary : { total: warningCount },
                        highlightColor: 'warning',
                        key: 'doctor-rrweb-warnings',
                    })
                }

                return items
            },
            { resultEqualityCheck: equal },
        ],

        allContextItems: [
            (s) => [
                s.start,
                s.processedSnapshotData,
                s.windowNumberForID,
                s.sessionPlayerMetaData,
                s.segments,
                s.runtimeDoctorEvents,
            ],
            (start, processedSnapshotData, windowNumberForID, sessionPlayerMetaData, segments, runtimeDoctorEvents) => {
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

                // Add runtime doctor events (asset errors, rrweb warnings)
                items.push(...runtimeDoctorEvents)

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
            { resultEqualityCheck: equal },
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
                s.uuidToIndex,
                s.logs,
