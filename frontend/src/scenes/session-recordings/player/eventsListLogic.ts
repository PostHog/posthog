import { kea } from 'kea'
import { PlayerPosition, RecordingEventsFilters, RecordingEventType } from '~/types'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import type { eventsListLogicType } from './eventsListLogicType'
import { clamp, colonDelimitedDuration, findLastIndex, floorMsToClosestSecond, ceilMsToClosestSecond } from 'lib/utils'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import List, { RenderedRows } from 'react-virtualized/dist/es/List'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export const DEFAULT_ROW_HEIGHT = 65 // Two lines
export const OVERSCANNED_ROW_COUNT = 50
export const DEFAULT_SCROLLING_RESET_TIME_INTERVAL = 150 * 5 // https://github.com/bvaughn/react-virtualized/blob/abe0530a512639c042e74009fbf647abdb52d661/source/Grid/Grid.js#L42

export const eventsListLogic = kea<eventsListLogicType>({
    path: ['scenes', 'session-recordings', 'player', 'eventsListLogic'],
    connect: {
        logic: [eventUsageLogic],
        actions: [sessionRecordingLogic, ['setFilters', 'loadEventsSuccess'], sessionRecordingPlayerLogic, ['seek']],
        values: [
            sessionRecordingLogic,
            ['eventsToShow', 'sessionEventsDataLoading'],
            sessionRecordingPlayerLogic,
            ['currentPlayerTime'],
        ],
    },
    actions: {
        setLocalFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        setRenderedRows: (renderMeta: RenderedRows) => ({ renderMeta }),
        setList: (list: List) => ({ list }),
        enablePositionFinder: true,
        disablePositionFinder: true,
        scrollTo: (rowIndex?: number) => ({ rowIndex }),
        handleEventClick: (playerPosition: PlayerPosition) => ({ playerPosition }),
    },
    reducers: {
        localFilters: [
            {} as Partial<RecordingEventsFilters>,
            {
                setLocalFilters: (state, { filters }) => ({ ...state, ...filters }),
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
    },
    listeners: ({ actions, values }) => ({
        setLocalFilters: async (_, breakpoint) => {
            await breakpoint(250)
            actions.setFilters(values.localFilters)
        },
        scrollTo: async ({ rowIndex: _rowIndex }, breakpoint) => {
            const rowIndex = _rowIndex ?? values.currentEventsIndices.startIndex
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
    }),
    selectors: () => ({
        listEvents: [
            (selectors) => [selectors.eventsToShow],
            (events: RecordingEventType[]): RecordingEventType[] => {
                return events.map((e) => ({
                    ...e,
                    colonTimestamp: colonDelimitedDuration(Math.floor((e.playerTime ?? 0) / 1000)),
                }))
            },
        ],
        currentEventStartIndex: [
            (selectors) => [selectors.listEvents, selectors.currentPlayerTime],
            (events, currentPlayerTime): number => {
                return events.findIndex((e) => (e.playerTime ?? 0) >= ceilMsToClosestSecond(currentPlayerTime ?? 0))
            },
        ],
        currentEventsTimeRange: [
            (selectors) => [selectors.currentEventStartIndex, selectors.listEvents, selectors.currentPlayerTime],
            (startIndex, events, currentPlayerTime) => {
                if (events.length < 1) {
                    return { start: 0, end: 0 }
                }
                const end = Math.max(ceilMsToClosestSecond(currentPlayerTime ?? 0), 1000)
                const start = floorMsToClosestSecond(
                    events[clamp(startIndex === -1 ? events.length - 1 : startIndex - 1, 0, events.length - 1)]
                        .playerTime ?? 0
                )

                return { start, end }
            },
        ],
        isEventCurrent: [
            (selectors) => [selectors.currentEventsTimeRange, selectors.listEvents],
            (indices, events) => (index: number) =>
                (events?.[index]?.playerTime ?? 0) >= indices.start && (events?.[index]?.playerTime ?? 0) < indices.end,
        ],
        currentEventsIndices: [
            (selectors) => [selectors.listEvents, selectors.isEventCurrent],
            (events, isEventCurrent) => ({
                startIndex: clamp(
                    events.findIndex((_, i) => isEventCurrent(i)),
                    0,
                    events.length - 1
                ),
                stopIndex: clamp(
                    findLastIndex(events, (_, i) => isEventCurrent(i)),
                    0,
                    events.length - 1
                ),
            }),
        ],
        currentEventsBoxSizeAndPosition: [
            (selectors) => [selectors.currentEventsIndices, selectors.list],
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
            (selectors) => [selectors.renderedRows, selectors.currentEventsIndices, selectors.shouldHidePositionFinder],
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
            (selectors) => [selectors.renderedRows, selectors.currentEventsIndices],
            (visibleRange, currentEventsRange) => {
                // Where are we relative to the current event
                return visibleRange.startIndex > currentEventsRange.stopIndex
            },
        ],
    }),
})
