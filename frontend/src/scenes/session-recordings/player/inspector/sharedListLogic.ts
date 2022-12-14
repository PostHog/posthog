import { actions, kea, reducers, path, listeners, connect, props, key, selectors } from 'kea'
import {
    PerformanceEvent,
    PlayerPosition,
    RecordingConsoleLog,
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

export type WindowOption = RecordingWindowFilter.All | PlayerPosition['windowId']

type SharedListItemBase = {
    timestamp: Date
    search: string
}

type SharedListItemEvent = SharedListItemBase & {
    type: 'event'
    data: RecordingEventType
}

type SharedListItemConsole = SharedListItemBase & {
    type: 'console'
    data: RecordingConsoleLog
}

type SharedListItemPerformance = SharedListItemBase & {
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
        values: [playerSettingsLogic, ['showOnlyMatching'], sessionRecordingDataLogic(props), ['peformanceEvents']],
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
            SessionRecordingPlayerTab.EVENTS as SessionRecordingPlayerTab,
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
        allItems: [
            (s) => [s.peformanceEvents],
            (peformanceEvents): SharedListItem[] => {
                console.log({ peformanceEvents })
                const items: SharedListItem[] = []

                for (const event of peformanceEvents || []) {
                    items.push({
                        type: 'performance',
                        timestamp: new Date(),
                        search: event.name || '',
                        data: event,
                    })
                }

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

        fuse: [
            (s) => [s.allItems],
            (allItems): Fuse<SharedListItem> =>
                new Fuse<SharedListItem>(allItems, {
                    threshold: 0.3,
                    keys: ['search'],
                    findAllMatches: true,
                    ignoreLocation: true,
                    sortFn: (a, b) => a.score - b.score,
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
