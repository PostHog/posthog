import { actions, connect, kea, key, listeners, path, reducers, selectors, props } from 'kea'
import { PlayerPosition, RecordingEventsFilters, RecordingEventType } from '~/types'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import type { eventsListLogicType } from './eventsListLogicType'
import {
    clamp,
    colonDelimitedDuration,
    findLastIndex,
    floorMsToClosestSecond,
    ceilMsToClosestSecond,
    eventToDescription,
} from 'lib/utils'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import List, { RenderedRows } from 'react-virtualized/dist/es/List'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import Fuse from 'fuse.js'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import { RowStatus } from 'scenes/session-recordings/player/inspector/v1/listLogic'

export const DEFAULT_SCROLLING_RESET_TIME_INTERVAL = 150 * 5 // https://github.com/bvaughn/react-virtualized/blob/abe0530a512639c042e74009fbf647abdb52d661/source/Grid/Grid.js#L42

const makeEventsQueryable = (events: RecordingEventType[]): RecordingEventType[] => {
    return events.map((e) => ({
        ...e,
        queryValue: `${getKeyMapping(e.event, 'event')?.label ?? e.event ?? ''} ${eventToDescription(e)}`.replace(
            /['"]+/g,
            ''
        ),
    }))
}

export const eventsListLogic = kea<eventsListLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'eventsListLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect(({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps) => ({
        logic: [eventUsageLogic],
        actions: [
            sessionRecordingDataLogic({ sessionRecordingId }),
            ['setFilters'],
            sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }),
            ['seek'],
        ],
        values: [
            sessionRecordingDataLogic({ sessionRecordingId }),
            ['filters', 'sessionEventsData', 'sessionEventsDataLoading'],
            sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }),
            ['currentPlayerTime', 'matchingEvents'],
            playerInspectorLogic({ sessionRecordingId, playerKey }),
            ['windowIdFilter', 'showOnlyMatching'],
        ],
    })),
    actions({
        setEventListLocalFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        setRenderedRows: (renderMeta: RenderedRows) => ({ renderMeta }),
        setList: (list: List) => ({ list }),
        enablePositionFinder: true,
        disablePositionFinder: true,
        scrollTo: (rowIndex?: number) => ({ rowIndex }),
        handleEventClick: (playerPosition: PlayerPosition) => ({ playerPosition }),
    }),
    reducers({
        eventListLocalFilters: [
            {} as Partial<RecordingEventsFilters>,
            {
                setEventListLocalFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        renderedRows: [
            {
                startIndex: 0,
                stopIndex: 0,
                overscanStartIndex: 0,
                overscanStopIndex: 0,
            } as RenderedRows,
            {
                setRenderedRows: (_, { renderMeta }) => renderMeta,
            },
        ],
        list: [
            null as List | null,
            {
                setList: (_, { list }) => list,
            },
        ],
        shouldHidePositionFinder: [
            false,
            {
                scrollTo: () => true,
                enablePositionFinder: () => false,
                disablePositionFinder: () => true,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setEventListLocalFilters: async (_, breakpoint) => {
            await breakpoint(250)
            actions.setFilters(values.eventListLocalFilters)
        },
        scrollTo: async ({ rowIndex: _rowIndex }, breakpoint) => {
            const rowIndex = _rowIndex ?? values.currentIndices.startIndex
            if (values.list) {
                values.list.scrollToPosition(values.list.getOffsetForRow({ alignment: 'center', index: rowIndex }))
                eventUsageLogic.actions.reportRecordingScrollTo(rowIndex)
            }
            // Enable position finder so that it can become visible again. Turning it off at scroll start
            // makes sure that it stays hidden for the duration of the auto scroll.
            await breakpoint(DEFAULT_SCROLLING_RESET_TIME_INTERVAL)
            actions.enablePositionFinder()
        },
        handleEventClick: ({ playerPosition }) => {
            if (playerPosition) {
                actions.seek(playerPosition)
            }
        },
    })),
    selectors(() => ({
        eventListData: [
            (selectors) => [
                selectors.sessionEventsData,
                selectors.filters,
                selectors.windowIdFilter,
                selectors.matchingEvents,
                selectors.showOnlyMatching,
            ],
            (sessionEventsData, filters, windowIdFilter, matchingEvents, showOnlyMatching): RecordingEventType[] => {
                const eventsBeforeFiltering: RecordingEventType[] = sessionEventsData?.events ?? []
                const events: RecordingEventType[] = filters?.query
                    ? new Fuse<RecordingEventType>(makeEventsQueryable(eventsBeforeFiltering), {
                          threshold: 0.3,
                          keys: ['queryValue'],
                          findAllMatches: true,
                          ignoreLocation: true,
                          sortFn: (a, b) =>
                              parseInt(eventsBeforeFiltering[a.idx].timestamp) -
                                  parseInt(eventsBeforeFiltering[b.idx].timestamp) || a.score - b.score,
                      })
                          .search(filters.query)
                          .map((result) => result.item)
                    : eventsBeforeFiltering

                const matchingEventIds = new Set(matchingEvents.map((e) => e.uuid))
                const shouldShowOnlyMatching = matchingEvents.length > 0 && showOnlyMatching

                return events
                    .filter(
                        (e) =>
                            (!windowIdFilter || e.playerPosition?.windowId === windowIdFilter) &&
                            (!shouldShowOnlyMatching || matchingEventIds.has(String(e.id)))
                    )
                    .map((e) => ({
                        ...e,
                        colonTimestamp: colonDelimitedDuration(Math.floor((e.playerTime ?? 0) / 1000)),
                        level: matchingEventIds.has(String(e.id)) ? RowStatus.Match : undefined,
                    }))
            },
        ],
        currentStartIndex: [
            (selectors) => [selectors.eventListData, selectors.currentPlayerTime],
            (eventListData, currentPlayerTime): number => {
                return eventListData.findIndex(
                    (e) => (e.playerTime ?? 0) >= ceilMsToClosestSecond(currentPlayerTime ?? 0)
                )
            },
        ],
        currentTimeRange: [
            (selectors) => [selectors.currentStartIndex, selectors.eventListData, selectors.currentPlayerTime],
            (startIndex, eventListData, currentPlayerTime) => {
                if (eventListData.length < 1) {
                    return { start: 0, end: 0 }
                }
                const end = Math.max(ceilMsToClosestSecond(currentPlayerTime ?? 0), 1000)
                const start = floorMsToClosestSecond(
                    eventListData[
                        clamp(
                            startIndex === -1 ? eventListData.length - 1 : startIndex - 1,
                            0,
                            eventListData.length - 1
                        )
                    ].playerTime ?? 0
                )

                return { start, end }
            },
        ],
        isCurrent: [
            (selectors) => [selectors.currentTimeRange, selectors.eventListData],
            (indices, eventListData) => (index: number) =>
                (eventListData?.[index]?.playerTime ?? 0) >= indices.start &&
                (eventListData?.[index]?.playerTime ?? 0) < indices.end,
        ],
        currentIndices: [
            (selectors) => [selectors.eventListData, selectors.isCurrent],
            (eventListData, isCurrent) => ({
                startIndex: clamp(
                    eventListData.findIndex((_, i) => isCurrent(i)),
                    0,
                    eventListData.length - 1
                ),
                stopIndex: clamp(
                    findLastIndex(eventListData, (_, i) => isCurrent(i)),
                    0,
                    eventListData.length - 1
                ),
            }),
        ],
        currentBoxSizeAndPosition: [
            (selectors) => [selectors.currentIndices, selectors.list],
            (indices, list) => {
                if (
                    !list ||
                    !list.Grid ||
                    indices.startIndex >= list.Grid.props.rowCount ||
                    indices.stopIndex > list.Grid.props.rowCount ||
                    (indices.startIndex < 1 && indices.stopIndex < 1) ||
                    indices.stopIndex < indices.startIndex
                ) {
                    return {
                        top: 0,
                        height: 0,
                    }
                }

                const gridState = list.Grid.state as any
                const top = gridState.instanceProps.rowSizeAndPositionManager.getSizeAndPositionOfCell(
                    indices.startIndex
                ).offset
                const lastEventSize = gridState.instanceProps.rowSizeAndPositionManager.getSizeAndPositionOfCell(
                    indices.stopIndex
                )
                return {
                    top,
                    height: lastEventSize.offset + lastEventSize.size - top,
                }
            },
        ],
        isRowIndexRendered: [
            (selectors) => [selectors.renderedRows],
            (renderedRows) => (index: number) =>
                index >= renderedRows.overscanStartIndex && index <= renderedRows.overscanStopIndex,
        ],
        showPositionFinder: [
            (selectors) => [selectors.renderedRows, selectors.currentIndices, selectors.shouldHidePositionFinder],
            (visibleRange, currentEventsRange, shouldHidePositionFinder) => {
                // Only show finder if there's no overlap of view range and current events range
                return (
                    !shouldHidePositionFinder &&
                    (visibleRange.stopIndex < currentEventsRange.startIndex ||
                        visibleRange.startIndex > currentEventsRange.stopIndex)
                )
            },
        ],
        isDirectionUp: [
            (selectors) => [selectors.renderedRows, selectors.currentIndices],
            (visibleRange, currentEventsRange) => {
                // Where are we relative to the current event
                return visibleRange.startIndex > currentEventsRange.stopIndex
            },
        ],
    })),
])
