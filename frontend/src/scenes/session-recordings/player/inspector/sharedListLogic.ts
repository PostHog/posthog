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

export type WindowOption = RecordingWindowFilter.All | PlayerPosition['windowId']

type SharedListItemBase = {
    timestamp: Dayjs
    timeInRecording: number
    search: string
}

export type SharedListItemEvent = SharedListItemBase & {
    type: 'event'
    data: RecordingEventType
}

export type SharedListItemConsole = SharedListItemBase & {
    type: 'console'
    data: RecordingConsoleLogBase
}

export type SharedListItemPerformance = SharedListItemBase & {
    type: 'performance'
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
        values: [
            playerSettingsLogic,
            ['showOnlyMatching'],
            sessionRecordingDataLogic(props),
            ['peformanceEvents', 'consoleLogs', 'sessionPlayerMetaData'],
        ],
        actions: [playerSettingsLogic, ['setShowOnlyMatching']],
    })),
    actions(() => ({
        setTab: (tab: SessionRecordingPlayerTab) => ({ tab }),
        setWindowIdFilter: (windowId: WindowOption) => ({ windowId }),
        setSearchQuery: (search: string) => ({ search }),
    })),
    reducers(() => ({
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
            SessionRecordingPlayerTab.ALL as SessionRecordingPlayerTab,
            {
                setTab: (_, { tab }) => tab,
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
        V2Tabs: [
            (s) => [s.tab],
            (tab): SessionRecordingPlayerTab[] => {
                return [
                    SessionRecordingPlayerTab.ALL,
                    SessionRecordingPlayerTab.CONSOLE,
                    SessionRecordingPlayerTab.PERFORMANCE,
                ]
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
            (s) => [s.tab, s.recordingTimeInfo, s.peformanceEvents, s.consoleLogs],
            (tab, recordingTimeInfo, peformanceEvents, consoleLogs): SharedListItem[] => {
                const items: SharedListItem[] = []

                if (tab === SessionRecordingPlayerTab.ALL || tab === SessionRecordingPlayerTab.PERFORMANCE) {
                    for (const event of peformanceEvents || []) {
                        const timestamp = dayjs(event.timestamp)
                        items.push({
                            type: 'performance',
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
                            type: 'console',
                            timestamp,
                            timeInRecording: timestamp.diff(recordingTimeInfo.start, 'ms'),
                            search: event.rawString,
                            data: event,
                        })
                    }
                }

                items.sort((a, b) => a.timestamp.diff(b.timestamp))

                return items

                // const events: RecordingEventType[] = filters?.query
                //     ? new Fuse<RecordingEventType>(makeEventsQueryable(eventsBeforeFiltering), {
                //           threshold: 0.3,
                //           keys: ['queryValue'],
                //           findAllMatches: true,
                //           ignoreLocation: true,
                //           sortFn: (a, b) =>
                //               parseInt(eventsBeforeFiltering[a.idx].timestamp) -
                //                   parseInt(eventsBeforeFiltering[b.idx].timestamp) || a.score - b.score,
                //       })
                //           .search(filters.query)
                //           .map((result) => result.item)
                //     : eventsBeforeFiltering

                // const matchingEventIds = new Set(matchingEvents.map((e) => e.uuid))
                // const shouldShowOnlyMatching = matchingEvents.length > 0 && showOnlyMatching

                // return events
                //     .filter(
                //         (e) =>
                //             (windowIdFilter === RecordingWindowFilter.All ||
                //                 e.playerPosition?.windowId === windowIdFilter) &&
                //             (!shouldShowOnlyMatching || matchingEventIds.has(String(e.id)))
                //     )
                //     .map((e) => ({
                //         ...e,
                //         colonTimestamp: colonDelimitedDuration(Math.floor((e.playerTime ?? 0) / 1000)),
                //         level: matchingEventIds.has(String(e.id)) ? RowStatus.Match : undefined,
                //     }))
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
                const items = fuse.search(searchQuery).map((x) => x.item)

                return items
            },
        ],
    })),
])
