import { customEvent, EventType, eventWithTime, fullSnapshotEvent, pluginEvent } from '@posthog/rrweb-types'
import FuseClass from 'fuse.js'
import { actions, connect, events, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventToDescription, humanizeBytes, objectsEqual, toParams } from 'lib/utils'
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
    convertUniversalFiltersToRecordingsQuery,
    MatchingEventsMatchType,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import {
    AnnotationType,
    FilterableInspectorListItemTypes,
    MatchedRecordingEvent,
    PerformanceEvent,
    RecordingConsoleLogV2,
    RecordingEventType,
    RRWebRecordingConsoleLogPayload,
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

export type RecordingComment = {
    id: string
    notebookShortId: string
    notebookTitle: string
    comment: string
    timeInRecording: number
}

export type InspectorListItemBase = {
    timestamp: Dayjs
    timeInRecording: number
    search: string
    highlightColor?: 'danger' | 'warning' | 'primary'
    windowId?: string
    windowNumber?: number | '?' | undefined
}

export type InspectorListItemType = InspectorListItem['type']

export type InspectorListItemEvent = InspectorListItemBase & {
    type: FilterableInspectorListItemTypes.EVENTS
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

export type InspectorListItemAnnotationComment = InspectorListItemBase & {
    type: 'comment'
    source: 'annotation'
    data: AnnotationType
}

export type InspectorListItemComment = InspectorListItemNotebookComment | InspectorListItemAnnotationComment

export type InspectorListItemConsole = InspectorListItemBase & {
    type: FilterableInspectorListItemTypes.CONSOLE
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
    type: FilterableInspectorListItemTypes.DOCTOR
    tag: string
    data?: Record<string, any>
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
    | InspectorListItemSummary
    | InspectorListItemInactivity

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
    thingWithTime:
        | eventWithTime
        | PerformanceEvent
        | RecordingConsoleLogV2
        | RecordingEventType
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
            miniFiltersLogic,
            ['setMiniFilter', 'setSearchQuery'],
            sessionRecordingEventUsageLogic,
            ['reportRecordingInspectorItemExpanded'],
            sessionRecordingDataLogic(props),
            ['loadFullEventData', 'setTrackedWindow', 'sessionAnnotations'],
        ],
        values: [
            miniFiltersLogic,
            ['showOnlyMatching', 'miniFiltersByKey', 'searchQuery', 'miniFiltersForTypeByKey', 'miniFilters'],
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
                'sessionPlayerMetaData',
                'segments',
            ],
            sessionRecordingPlayerLogic(props),
            ['currentPlayerTime'],
            performanceEventDataLogic({ key: props.playerKey, sessionRecordingId: props.sessionRecordingId }),
            ['allPerformanceEvents'],
            sessionRecordingDataLogic(props),
            ['trackedWindow'],
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

                    const params: RecordingsQuery = {
                        ...convertUniversalFiltersToRecordingsQuery(filters),
                        session_ids: [props.sessionRecordingId],
                    }

                    const response = await api.recordings.getMatchingEvents(toParams(params))
                    return response.results.map((x) => ({ uuid: x } as MatchedRecordingEvent))
                },
            },
        ],
    })),
    selectors(({ props }) => ({
        allowMatchingEventsFilter: [
            (s) => [s.miniFilters],
            (miniFilters): boolean => {
                return (
                    miniFilters.some((mf) => mf.type === FilterableInspectorListItemTypes.EVENTS && mf.enabled) &&
                    props.matchingEventsMatchType?.matchType !== 'none'
                )
            },
        ],

        windowNumberForID: [
            (s) => [s.windowIds],
            (windowIds) => {
                return (windowId: string | undefined): number | '?' | undefined => {
                    return windowIds.length > 1 ? (windowId ? windowIds.indexOf(windowId) + 1 || '?' : '?') : undefined
                }
            },
        ],

        offlineStatusChanges: [
            (s) => [s.start, s.sessionPlayerData, s.windowNumberForID],
            (start, sessionPlayerData, windowNumberForID): InspectorListOfflineStatusChange[] => {
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
                                    windowNumber: windowNumberForID(windowId),
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
            (s) => [s.start, s.sessionPlayerData, s.windowNumberForID],
            (start, sessionPlayerData, windowNumberForID): InspectorListBrowserVisibility[] => {
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
                                    windowNumber: windowNumberForID(windowId),
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
            (s) => [s.start, s.sessionPlayerData, s.windowNumberForID],
            (start, sessionPlayerData, windowNumberForID): InspectorListItemDoctor[] => {
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

                            if (
                                [
                                    '$pageview',
                                    'window hidden',
                                    'browser offline',
                                    'browser online',
                                    'window visible',
                                ].includes(tag)
                            ) {
                                return
                            }

                            const { timestamp, timeInRecording } = timeRelativeToStart(snapshot, start)

                            items.push({
                                type: FilterableInspectorListItemTypes.DOCTOR,
                                timestamp,
                                timeInRecording,
                                tag: niceify(tag),
                                search: niceify(tag),
                                window_id: windowId,
                                windowId: windowId,
                                windowNumber: windowNumberForID(windowId),
                                data: getPayloadFor(customEvent, tag),
                            })
                        }
                        if (isFullSnapshotEvent(snapshot)) {
                            const { timestamp, timeInRecording } = timeRelativeToStart(snapshot, start)

                            items.push({
                                type: FilterableInspectorListItemTypes.DOCTOR,
                                timestamp,
                                timeInRecording,
                                tag: 'full snapshot event',
                                search: 'full snapshot event',
                                window_id: windowId,
                                windowId: windowId,
                                windowNumber: windowNumberForID(windowId),
                                data: { snapshotSize: humanizeBytes(estimateSize(snapshot)) },
                            })
                        }
                    })
                })

                items.push({
                    type: FilterableInspectorListItemTypes.DOCTOR,
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
            (s) => [s.sessionPlayerData, s.windowNumberForID],
            (sessionPlayerData, windowNumberForID): RecordingConsoleLogV2[] => {
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
                                windowNumber: windowNumberForID(windowId),
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

        annotationItems: [
            (s) => [s.sessionAnnotations, s.windowIdForTimestamp, s.windowNumberForID],
            (sessionAnnotations, windowIdForTimestamp, windowNumberForID): InspectorListItem[] => {
                const items: InspectorListItemComment[] = []
                for (const annotation of sessionAnnotations || []) {
                    const windowId = windowIdForTimestamp(annotation.timestamp.valueOf())
                    items.push({
                        ...annotation,
                        highlightColor: 'primary',
                        windowId: windowId,
                        windowNumber: windowNumberForID(windowId),
                    })
                }
                return items
            },
        ],

        allContextItems: [
            (s) => [
                s.start,
                s.offlineStatusChanges,
                s.doctorEvents,
                s.browserVisibilityChanges,
                s.sessionComments,
                s.windowIdForTimestamp,
                s.windowNumberForID,
                s.sessionPlayerMetaData,
                s.segments,
                s.annotationItems,
            ],
            (
                start,
                offlineStatusChanges,
                doctorEvents,
                browserVisibilityChanges,
                sessionComments,
                windowIdForTimestamp,
                windowNumberForID,
                sessionPlayerMetaData,
                segments,
                annotationItems
            ) => {
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
                        })
                    })

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

                // no conversion needed for annotations, they're ready to roll
                for (const annotation of annotationItems || []) {
                    items.push(annotation)
                }

                for (const comment of sessionComments || []) {
                    const { timestamp, timeInRecording } = commentTimestamp(comment, start)
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
                        })
                    }
                }

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
                    })
                }

                // NOTE: Native JS sorting is relatively slow here - be careful changing this
                items.sort((a, b) => (a.timestamp.valueOf() > b.timestamp.valueOf() ? 1 : -1))

                return items
            },
        ],

        allItems: [
            (s) => [
                s.start,
                s.allPerformanceEvents,
                s.consoleLogs,
                s.sessionEventsData,
                s.matchingEventUUIDs,
                s.windowNumberForID,
                s.allContextItems,
            ],
            (
                start,
                performanceEvents,
                consoleLogs,
                eventsData,
                matchingEventUUIDs,
                windowNumberForID,
                allContextItems
            ): InspectorListItem[] => {
                // NOTE: Possible perf improvement here would be to have a selector to parse the items
                // and then do the filtering of what items are shown, elsewhere
                // ALSO: We could move the individual filtering logic into the MiniFilters themselves
                // WARNING: Be careful of dayjs functions - they can be slow due to the size of the loop.
                const items: InspectorListItem[] = []

                // PERFORMANCE EVENTS
                const performanceEventsArr = performanceEvents || []
                for (const event of performanceEventsArr) {
                    const responseStatus = event.response_status || null

                    if (event.entry_type === 'paint') {
                        // We don't include paint events as they are covered in the navigation events
                        continue
                    }

                    const { timestamp, timeInRecording } = timeRelativeToStart(event, start)
                    items.push({
                        type: FilterableInspectorListItemTypes.NETWORK,
                        timestamp,
                        timeInRecording,
                        search: event.name || '',
                        data: event,
                        highlightColor: (responseStatus || 0) >= 400 ? 'danger' : undefined,
                        windowId: event.window_id,
                        windowNumber: windowNumberForID(event.window_id),
                    })
                }

                // CONSOLE LOGS
                for (const event of consoleLogs || []) {
                    const { timestamp, timeInRecording } = timeRelativeToStart(event, start)
                    items.push({
                        type: FilterableInspectorListItemTypes.CONSOLE,
                        timestamp,
                        timeInRecording,
                        search: event.content,
                        data: event,
                        highlightColor:
                            event.level === 'error' ? 'danger' : event.level === 'warn' ? 'warning' : undefined,
                        windowId: event.windowId,
                        windowNumber: windowNumberForID(event.windowId),
                    })
                }

                let errorCount = 0
                for (const event of eventsData || []) {
                    let isMatchingEvent = false

                    if (event.event === '$exception') {
                        errorCount += 1
                    }

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
                        type: FilterableInspectorListItemTypes.EVENTS,
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
                        windowNumber: windowNumberForID(event.properties?.$window_id),
                    })
                }

                for (const event of allContextItems || []) {
                    items.push(event)
                }

                // NOTE: Native JS sorting is relatively slow here - be careful changing this
                items.sort((a, b) => (a.timestamp.valueOf() > b.timestamp.valueOf() ? 1 : -1))

                // ensure that item with type 'inspector-summary' is always at the top
                const summary: InspectorListItemSummary | undefined = items.find(
                    (item) => item.type === 'inspector-summary'
                ) as InspectorListItemSummary | undefined
                if (summary) {
                    summary.errorCount = errorCount
                    items.splice(items.indexOf(summary), 1)
                    items.unshift(summary)
                }
                if (items.length > 0) {
                    items[0].windowNumber = items[1]?.windowNumber
                    items[0].windowId = items[1]?.windowId
                }

                return items
            },
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
                allItems,
                miniFiltersByKey,
                showOnlyMatching,
                allowMatchingEventsFilter,
                trackedWindow,
                hasEventsToDisplay
            ): InspectorListItem[] => {
                const filteredItems = filterInspectorListItems({
                    allItems,
                    miniFiltersByKey,
                    allowMatchingEventsFilter,
                    showOnlyMatching,
                    trackedWindow,
                    hasEventsToDisplay,
                })

                // need to collapse adjacent inactivity items
                // they look werong next to each other
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
        ],

        seekbarItems: [
            (s) => [
                s.allItems,
                s.miniFiltersForTypeByKey,
                s.showOnlyMatching,
                s.allowMatchingEventsFilter,
                s.trackedWindow,
                s.hasEventsToDisplay,
            ],
            (
                allItems,
                miniFiltersForTypeByKey,
                showOnlyMatching,
                allowMatchingEventsFilter,
                trackedWindow,
                hasEventsToDisplay
            ): (InspectorListItemEvent | InspectorListItemComment)[] => {
                const eventFilteredItems = filterInspectorListItems({
                    allItems,
                    miniFiltersByKey: miniFiltersForTypeByKey(FilterableInspectorListItemTypes.EVENTS),
                    allowMatchingEventsFilter,
                    showOnlyMatching,
                    trackedWindow,
                    hasEventsToDisplay,
                })

                let items: (InspectorListItemEvent | InspectorListItemComment)[] = eventFilteredItems.filter(
                    (item): item is InspectorListItemEvent | InspectorListItemComment => {
                        if (item.type === FilterableInspectorListItemTypes.EVENTS) {
                            return !(allowMatchingEventsFilter && showOnlyMatching && item.highlightColor !== 'primary')
                        }

                        if (item.type === 'comment') {
                            return !allowMatchingEventsFilter
                        }

                        return false
                    }
                )

                if (items.length > MAX_SEEKBAR_ITEMS) {
                    items = items.filter((item) => {
                        const isPrimary = item.highlightColor === 'primary'
                        const isPageView =
                            item.type === FilterableInspectorListItemTypes.EVENTS && item.data.event === '$pageview'
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

        inspectorDataState: [
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
            ): Record<FilterableInspectorListItemTypes, 'loading' | 'ready' | 'empty'> => {
                const dataForEventsState = sessionEventsDataLoading ? 'loading' : events?.length ? 'ready' : 'empty'
                const dataForConsoleState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !logs
                        ? 'loading'
                        : logs.length
                        ? 'ready'
                        : 'empty'
                const dataForNetworkState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !performanceEvents
                        ? 'loading'
                        : performanceEvents.length
                        ? 'ready'
                        : 'empty'
                const dataForDoctorState =
                    sessionPlayerMetaDataLoading || snapshotsLoading || !performanceEvents
                        ? 'loading'
                        : doctorEvents.length
                        ? 'ready'
                        : 'empty'
                return {
                    [FilterableInspectorListItemTypes.EVENTS]: dataForEventsState,
                    [FilterableInspectorListItemTypes.CONSOLE]: dataForConsoleState,
                    [FilterableInspectorListItemTypes.NETWORK]: dataForNetworkState,
                    [FilterableInspectorListItemTypes.DOCTOR]: dataForDoctorState,
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

        /**
         * All items by mini-filter key, not filtered items, so that we can count the unfiltered sets
         */
        allItemsByMiniFilterKey: [
            (s) => [s.allItems, s.miniFiltersByKey],
            (allItems, miniFiltersByKey): Record<MiniFilterKey, InspectorListItem[]> => {
                const itemsByMiniFilterKey: Record<MiniFilterKey, InspectorListItem[]> = {
                    'events-posthog': [],
                    'events-custom': [],
                    'events-pageview': [],
                    'events-autocapture': [],
                    'events-exceptions': [],
                    'console-info': [],
                    'console-warn': [],
                    'console-error': [],
                    'performance-fetch': [],
                    'performance-document': [],
                    'performance-assets-js': [],
                    'performance-assets-css': [],
                    'performance-assets-img': [],
                    'performance-other': [],
                    doctor: [],
                }

                for (const item of allItems) {
                    const miniFilter = itemToMiniFilter(item, miniFiltersByKey)
                    if (miniFilter) {
                        itemsByMiniFilterKey[miniFilter.key].push(item)
                    }
                }

                return itemsByMiniFilterKey
            },
        ],

        /**
         * All items by item type, not filtered items, so that we can count the unfiltered sets
         */
        allItemsByItemType: [
            (s) => [s.allItems],
            (allItems): Record<MiniFilterKey, InspectorListItem[]> => {
                const itemsByType: Record<FilterableInspectorListItemTypes | 'context', InspectorListItem[]> = {
                    [FilterableInspectorListItemTypes.EVENTS]: [],
                    [FilterableInspectorListItemTypes.CONSOLE]: [],
                    [FilterableInspectorListItemTypes.NETWORK]: [],
                    [FilterableInspectorListItemTypes.DOCTOR]: [],
                    context: [],
                }

                for (const item of allItems) {
                    itemsByType[
                        [
                            FilterableInspectorListItemTypes.EVENTS,
                            FilterableInspectorListItemTypes.CONSOLE,
                            FilterableInspectorListItemTypes.NETWORK,
                            FilterableInspectorListItemTypes.DOCTOR,
                        ].includes(item.type as FilterableInspectorListItemTypes)
                            ? item.type
                            : 'context'
                    ].push(item)
                }

                return itemsByType
            },
        ],

        hasEventsToDisplay: [
            (s) => [s.allItemsByItemType],
            (allItemsByItemType): boolean => allItemsByItemType[FilterableInspectorListItemTypes.EVENTS]?.length > 0,
        ],
    })),
    listeners(({ values, actions }) => ({
        setItemExpanded: ({ index, expanded }) => {
            if (expanded) {
                const item = values.items[index]
                actions.reportRecordingInspectorItemExpanded(item.type, index)

                if (item.type === FilterableInspectorListItemTypes.EVENTS) {
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
