import { actions, connect, events, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import {
    MatchedRecordingEvent,
    PerformanceEvent,
    RecordingConsoleLogV2,
    RecordingEventType,
    RRWebRecordingConsoleLogPayload,
    SessionRecordingPlayerTab,
} from '~/types'
import type { playerInspectorLogicType } from './playerInspectorLogicType'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import FuseClass from 'fuse.js'
import { Dayjs, dayjs } from 'lib/dayjs'
import { getKeyMapping } from 'lib/taxonomy'
import { eventToDescription, objectsEqual, toParams } from 'lib/utils'
import { eventWithTime } from '@rrweb/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

const CONSOLE_LOG_PLUGIN_NAME = 'rrweb/console@1'
const NETWORK_PLUGIN_NAME = 'posthog/network@1'
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

export const PerformanceEventReverseMapping: { [key: number]: keyof PerformanceEvent } = {
    // BASE_PERFORMANCE_EVENT_COLUMNS
    0: 'entry_type',
    1: 'time_origin',
    2: 'name',

    // RESOURCE_EVENT_COLUMNS
    3: 'start_time',
    4: 'redirect_start',
    5: 'redirect_end',
    6: 'worker_start',
    7: 'fetch_start',
    8: 'domain_lookup_start',
    9: 'domain_lookup_end',
    10: 'connect_start',
    11: 'secure_connection_start',
    12: 'connect_end',
    13: 'request_start',
    14: 'response_start',
    15: 'response_end',
    16: 'decoded_body_size',
    17: 'encoded_body_size',
    18: 'initiator_type',
    19: 'next_hop_protocol',
    20: 'render_blocking_status',
    21: 'response_status',
    22: 'transfer_size',

    // LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS
    23: 'largest_contentful_paint_element',
    24: 'largest_contentful_paint_render_time',
    25: 'largest_contentful_paint_load_time',
    26: 'largest_contentful_paint_size',
    27: 'largest_contentful_paint_id',
    28: 'largest_contentful_paint_url',

    // NAVIGATION_EVENT_COLUMNS
    29: 'dom_complete',
    30: 'dom_content_loaded_event',
    31: 'dom_interactive',
    32: 'load_event_end',
    33: 'load_event_start',
    34: 'redirect_count',
    35: 'navigation_type',
    36: 'unload_event_end',
    37: 'unload_event_start',

    // Added after v1
    39: 'duration',
    40: 'timestamp',
}

// Helping kea-typegen navigate the exported default class for Fuse
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
    type: SessionRecordingPlayerTab.NETWORK
    data: PerformanceEvent
}

export type InspectorListItem = InspectorListItemEvent | InspectorListItemConsole | InspectorListItemPerformance

export interface PlayerInspectorLogicProps extends SessionRecordingPlayerLogicProps {
    matchingEventsMatchType?: MatchingEventsMatchType
}

export const playerInspectorLogic = kea<playerInspectorLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerInspectorLogic', key]),
    props({} as PlayerInspectorLogicProps),
    key((props: PlayerInspectorLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: PlayerInspectorLogicProps) => ({
        actions: [
            playerSettingsLogic,
            ['setTab', 'setMiniFilter', 'setSyncScroll'],
            eventUsageLogic,
            ['reportRecordingInspectorItemExpanded'],
            sessionRecordingDataLogic(props),
            ['loadFullEventData'],
        ],
        values: [
            playerSettingsLogic,
            ['showOnlyMatching', 'tab', 'miniFiltersByKey', 'searchQuery'],
            sessionRecordingDataLogic(props),
            [
                'sessionPlayerData',
                'sessionPlayerMetaDataLoading',
                'sessionPlayerSnapshotDataLoading',
                'sessionEventsData',
                'sessionEventsDataLoading',
                'windowIds',
                'start',
                'end',
                'durationMs',
            ],
            sessionRecordingPlayerLogic(props),
            ['currentPlayerTime'],
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
            },
        ],

        syncScrollingPaused: [
            false,
            {
                setTab: () => false,
                setSyncScrollPaused: (_, { paused }) => paused,
                setItemExpanded: () => true,
                setSyncScroll: () => false,
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
                    const params = toParams({ ...filters, session_ids: [props.sessionRecordingId] })
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

        consoleLogs: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData): RecordingConsoleLogV2[] => {
                const logs: RecordingConsoleLogV2[] = []
                const seenCache = new Set<string>()

                Object.entries(sessionPlayerData.snapshotsByWindowId).forEach(([windowId, snapshots]) => {
                    snapshots.forEach((snapshot: eventWithTime) => {
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

        allPerformanceEvents: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData): PerformanceEvent[] => {
                // performanceEvents used to come from the API,
                // but we decided to instead store them in the recording data
                const events: PerformanceEvent[] = []

                Object.entries(sessionPlayerData.snapshotsByWindowId).forEach(([windowId, snapshots]) => {
                    snapshots.forEach((snapshot: eventWithTime) => {
                        if (
                            snapshot.type === 6 && // RRWeb plugin event type
                            snapshot.data.plugin === NETWORK_PLUGIN_NAME
                        ) {
                            const properties = snapshot.data.payload as any

                            const data: Partial<PerformanceEvent> = {
                                timestamp: snapshot.timestamp,
                                window_id: windowId,
                            }

                            Object.entries(PerformanceEventReverseMapping).forEach(([key, value]) => {
                                if (key in properties) {
                                    data[value] = properties[key]
                                }
                            })

                            events.push(data as PerformanceEvent)
                        }
                    })
                })

                return events
            },
        ],

        allItems: [
            (s) => [s.start, s.allPerformanceEvents, s.consoleLogs, s.sessionEventsData, s.matchingEventUUIDs],
            (start, performanceEvents, consoleLogs, eventsData, matchingEventUUIDs): InspectorListItem[] => {
                // NOTE: Possible perf improvement here would be to have a selector to parse the items
                // and then do the filtering of what items are shown, elsewhere
                // ALSO: We could move the individual filtering logic into the MiniFilters themselves
                const items: InspectorListItem[] = []

                // PERFORMANCE EVENTS
                const performanceEventsArr = performanceEvents || []
                for (const event of performanceEventsArr) {
                    const timestamp = dayjs(event.timestamp)
                    const responseStatus = event.response_status || 200

                    // NOTE: Navigation events are missing the first contentful paint info
                    // so, we find the relevant first contentful paint event and add it to the navigation event
                    if (event.entry_type === 'navigation' && !event.first_contentful_paint) {
                        const firstContentfulPaint = performanceEventsArr.find(
                            (x) =>
                                x.pageview_id === event.pageview_id &&
                                x.entry_type === 'paint' &&
                                x.name === 'first-contentful-paint'
                        )
                        if (firstContentfulPaint) {
                            event.first_contentful_paint = firstContentfulPaint.start_time
                        }
                    }

                    if (event.entry_type === 'paint') {
                        // We don't include paint events as they are covered in the navigation events
                        continue
                    }

                    items.push({
                        type: SessionRecordingPlayerTab.NETWORK,
                        timestamp,
                        timeInRecording: timestamp.diff(start, 'ms'),
                        search: event.name || '',
                        data: event,
                        highlightColor: responseStatus >= 400 ? 'danger' : undefined,
                        windowId: event.window_id,
                    })
                }

                // CONSOLE LOGS
                for (const event of consoleLogs || []) {
                    const timestamp = dayjs(event.timestamp)
                    items.push({
                        type: SessionRecordingPlayerTab.CONSOLE,
                        timestamp,
                        timeInRecording: timestamp.diff(start, 'ms'),
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

                    const timestamp = dayjs(event.timestamp)
                    const search = `${
                        getKeyMapping(event.event, 'event')?.label ?? event.event ?? ''
                    } ${eventToDescription(event)}`.replace(/['"]+/g, '')

                    items.push({
                        type: SessionRecordingPlayerTab.EVENTS,
                        timestamp,
                        timeInRecording: timestamp.diff(start, 'ms'),
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

                // NOTE: Native JS sorting is relatively slow here - be careful changing this
                items.sort((a, b) => (a.timestamp.isAfter(b.timestamp) ? 1 : -1))

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
                const items: InspectorListItem[] = []

                for (const item of allItems) {
                    let include = false

                    // EVENTS
                    if (item.type === SessionRecordingPlayerTab.EVENTS) {
                        if (tab !== SessionRecordingPlayerTab.EVENTS && tab !== SessionRecordingPlayerTab.ALL) {
                            continue
                        }

                        if (miniFiltersByKey['events-all']?.enabled || miniFiltersByKey['all-everything']?.enabled) {
                            include = true
                        }
                        if (miniFiltersByKey['events-posthog']?.enabled && item.data.event.startsWith('$')) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['events-custom']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            !item.data.event.startsWith('$')
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['events-pageview']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            ['$pageview', 'screen'].includes(item.data.event)
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['events-autocapture']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            item.data.event === '$autocapture'
                        ) {
                            include = true
                        }

                        if (
                            (miniFiltersByKey['all-errors']?.enabled ||
                                miniFiltersByKey['events-exceptions']?.enabled) &&
                            (item.data.event === '$exception' || item.data.event.toLowerCase().includes('error'))
                        ) {
                            include = true
                        }

                        if (showMatchingEventsFilter && showOnlyMatching) {
                            // Special case - overrides the others
                            include = include && item.highlightColor === 'primary'
                        }

                        if (windowIdFilter && item.data.properties?.$window_id !== windowIdFilter) {
                            include = false
                        }
                    }

                    // CONSOLE LOGS
                    if (item.type === SessionRecordingPlayerTab.CONSOLE) {
                        if (tab !== SessionRecordingPlayerTab.CONSOLE && tab !== SessionRecordingPlayerTab.ALL) {
                            continue
                        }

                        if (miniFiltersByKey['console-all']?.enabled || miniFiltersByKey['all-everything']?.enabled) {
                            include = true
                        }
                        if (miniFiltersByKey['console-info']?.enabled && ['log', 'info'].includes(item.data.level)) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['console-warn']?.enabled || miniFiltersByKey['all-automatic']?.enabled) &&
                            item.data.level === 'warn'
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['console-error']?.enabled ||
                                miniFiltersByKey['all-errors']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            item.data.level === 'error'
                        ) {
                            include = true
                        }

                        if (windowIdFilter && item.data.windowId !== windowIdFilter) {
                            include = false
                        }
                    }

                    // NETWORK
                    if (item.type === SessionRecordingPlayerTab.NETWORK) {
                        if (tab !== SessionRecordingPlayerTab.NETWORK && tab !== SessionRecordingPlayerTab.ALL) {
                            continue
                        }

                        const responseStatus = item.data.response_status || 200
                        const responseTime = item.data.duration || 0

                        if (
                            miniFiltersByKey['performance-all']?.enabled ||
                            miniFiltersByKey['all-everything']?.enabled
                        ) {
                            include = true
                        }
                        if (
                            (miniFiltersByKey['performance-document']?.enabled ||
                                miniFiltersByKey['all-automatic']?.enabled) &&
                            ['navigation'].includes(item.data.entry_type || '')
                        ) {
                            include = true
                        }
                        if (
                            miniFiltersByKey['performance-fetch']?.enabled &&
                            item.data.entry_type === 'resource' &&
                            ['fetch', 'xmlhttprequest'].includes(item.data.initiator_type || '')
                        ) {
                            include = true
                        }

                        if (
                            miniFiltersByKey['performance-assets-js']?.enabled &&
                            item.data.entry_type === 'resource' &&
                            (item.data.initiator_type === 'script' ||
                                (['link', 'other'].includes(item.data.initiator_type || '') &&
                                    item.data.name?.includes('.js')))
                        ) {
                            include = true
                        }

                        if (
                            miniFiltersByKey['performance-assets-css']?.enabled &&
                            item.data.entry_type === 'resource' &&
                            (item.data.initiator_type === 'css' ||
                                (['link', 'other'].includes(item.data.initiator_type || '') &&
                                    item.data.name?.includes('.css')))
                        ) {
                            include = true
                        }

                        if (
                            miniFiltersByKey['performance-assets-img']?.enabled &&
                            item.data.entry_type === 'resource' &&
                            (item.data.initiator_type === 'img' ||
                                (['link', 'other'].includes(item.data.initiator_type || '') &&
                                    !!IMAGE_WEB_EXTENSIONS.some((ext) => item.data.name?.includes(`.${ext}`))))
                        ) {
                            include = true
                        }

                        if (
                            miniFiltersByKey['performance-other']?.enabled &&
                            item.data.entry_type === 'resource' &&
                            ['other'].includes(item.data.initiator_type || '') &&
                            ![...IMAGE_WEB_EXTENSIONS, 'css', 'js'].some((ext) => item.data.name?.includes(`.${ext}`))
                        ) {
                            include = true
                        }

                        if (
                            (miniFiltersByKey['all-errors']?.enabled || miniFiltersByKey['all-automatic']?.enabled) &&
                            responseStatus >= 400
                        ) {
                            include = true
                        }

                        if (miniFiltersByKey['all-automatic']?.enabled && responseTime >= 1000) {
                            include = true
                        }

                        if (windowIdFilter && item.data.window_id !== windowIdFilter) {
                            include = false
                        }

                        if (item.data.entry_type === 'paint') {
                            // We don't include paint events as they are covered in the navigation events
                            include = false
                        }
                    }

                    if (!include) {
                        continue
                    }

                    items.push(item)
                }

                return items
            },
        ],

        seekbarItems: [
            (s) => [s.allItems, s.showOnlyMatching, s.showMatchingEventsFilter],
            (allItems, showOnlyMatching, showMatchingEventsFilter): InspectorListItemEvent[] => {
                let items = allItems.filter((item) => {
                    if (item.type !== SessionRecordingPlayerTab.EVENTS) {
                        return false
                    }

                    if (showMatchingEventsFilter && showOnlyMatching && item.highlightColor !== 'primary') {
                        return false
                    }

                    return true
                }) as InspectorListItemEvent[]

                if (items.length > MAX_SEEKBAR_ITEMS) {
                    items = items.filter((item) => {
                        return item.highlightColor === 'primary' || item.data.event === '$pageview'
                    })

                    items = items.filter((_, i) => {
                        if (i % Math.ceil(items.length / MAX_SEEKBAR_ITEMS) === 0) {
                            return true
                        }

                        return false
                    })
                }

                return items
            },
        ],

        tabsState: [
            (s) => [
                s.sessionEventsDataLoading,
                s.sessionPlayerMetaDataLoading,
                s.sessionPlayerSnapshotDataLoading,
                s.sessionEventsData,
                s.consoleLogs,
                s.allPerformanceEvents,
            ],
            (
                sessionEventsDataLoading,
                sessionPlayerMetaDataLoading,
                sessionPlayerSnapshotDataLoading,
                events,
                logs,
                performanceEvents
            ): Record<SessionRecordingPlayerTab, 'loading' | 'ready' | 'empty'> => {
                const tabEventsState = sessionEventsDataLoading ? 'loading' : events?.length ? 'ready' : 'empty'
                const tabConsoleState =
                    sessionPlayerMetaDataLoading || sessionPlayerSnapshotDataLoading || !logs
                        ? 'loading'
                        : logs.length
                        ? 'ready'
                        : 'empty'
                const tabNetworkState =
                    sessionPlayerMetaDataLoading || sessionPlayerSnapshotDataLoading || !performanceEvents
                        ? 'loading'
                        : performanceEvents.length
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
                }
            },
        ],

        playbackIndicatorIndex: [
            (s) => [s.currentPlayerTime, s.items],
            (playerTime, items): number => {
                // Returnts the index of the event that the playback is closest to
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
