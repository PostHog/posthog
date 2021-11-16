import { kea } from 'kea'
import { DEFAULT_SCROLLING_RESET_TIME_INTERVAL } from 'react-virtualized/dist/commonjs/Grid'
import { EventType, RecordingEventsFilters } from '~/types'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventsListLogicType } from './eventsListLogicType'
import { clamp, colonDelimitedDuration, findLastIndex, floorOrCeilMsToClosestSecond } from 'lib/utils'
import { CellMeasurerCache } from 'react-virtualized/dist/commonjs/CellMeasurer'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import List, { RenderedRows } from 'react-virtualized/dist/commonjs/List'

export const DEFAULT_ROW_HEIGHT = 50
export const OVERSCANNED_ROW_COUNT = 50

export const eventsListLogic = kea<eventsListLogicType>({
    path: ['scenes', 'session-recordings', 'player', 'eventsListLogic'],
    connect: {
        actions: [sessionRecordingLogic, ['setFilters', 'loadEventsSuccess']],
        values: [
            sessionRecordingLogic,
            ['eventsToShow', 'sessionEventsDataLoading'],
            sessionRecordingPlayerLogic,
            ['zeroOffsetTime'],
        ],
    },
    actions: {
        setLocalFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        setRenderedRows: (renderMeta: RenderedRows) => ({ renderMeta }),
        setList: (list: List) => ({ list }),
        clearCellCache: true,
        enablePositionFinder: true,
        scrollTo: (rowIndex?: number) => ({ rowIndex }),
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
            },
        ],
    },
    listeners: ({ cache, actions, values }) => ({
        setLocalFilters: async (_, breakpoint) => {
            await breakpoint(250)
            actions.setFilters(values.localFilters)
            actions.clearCellCache()
        },
        loadEventsSuccess: () => {
            actions.clearCellCache()
        },
        clearCellCache: async (_, breakpoint) => {
            await breakpoint(250)
            cache.cellMeasurerCache?.clearAll()
        },
        scrollTo: async ({ rowIndex: _rowIndex }, breakpoint) => {
            const rowIndex = _rowIndex ?? values.currentEventsIndices.startIndex
            if (values.list) {
                console.log(
                    'SCROLL TO',
                    values.list,
                    rowIndex,
                    values.list.getOffsetForRow({ alignment: 'center', index: rowIndex })
                )
                values.list.scrollToPosition(values.list.getOffsetForRow({ alignment: 'center', index: rowIndex }))
            }
            // Enable position finder so that it can become visible again. Turning it off at scroll start
            // makes sure that it stays hidden for the duration of the auto scroll.
            await breakpoint(DEFAULT_SCROLLING_RESET_TIME_INTERVAL)
            actions.enablePositionFinder()
        },
    }),
    selectors: ({ cache }) => ({
        listEvents: [
            (selectors) => [selectors.eventsToShow],
            (events: EventType[]) => {
                return events.map((e) => ({
                    ...e,
                    colonTimestamp: colonDelimitedDuration(Math.floor((e.zeroOffsetTime ?? 0) / 1000)),
                }))
            },
        ],
        cellMeasurerCache: [() => [], () => cache.cellMeasurerCache],
        currentEventsTimeRange: [
            (selectors) => [selectors.listEvents, selectors.zeroOffsetTime],
            (events, time) => {
                if (events.length < 1) {
                    return { start: 0, end: 0 }
                }
                const startIndex = events.findIndex(
                    (e) => (e.zeroOffsetTime ?? 0) > floorOrCeilMsToClosestSecond(time.current, false)
                )
                const end = floorOrCeilMsToClosestSecond(time.current, false)
                const start = floorOrCeilMsToClosestSecond(
                    events[clamp(startIndex === -1 ? events.length - 1 : startIndex - 1, 0, events.length - 1)]
                        .zeroOffsetTime ?? 0,
                    true
                )

                return { start, end }
            },
        ],
        isEventCurrent: [
            (selectors) => [selectors.currentEventsTimeRange, selectors.listEvents],
            (indices, events) => (index: number) =>
                (events?.[index]?.zeroOffsetTime ?? 0) >= indices.start &&
                (events?.[index]?.zeroOffsetTime ?? 0) < indices.end,
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
    events: ({ cache, actions }) => ({
        afterMount: () => {
            cache.cellMeasurerCache = new CellMeasurerCache({
                fixedWidth: true,
                defaultHeight: DEFAULT_ROW_HEIGHT,
            })
            window.addEventListener('resize', actions.clearCellCache)
        },
        afterUnmount: () => {
            cache.cellMeasurerCache = null
            window.removeEventListener('resize', actions.clearCellCache)
        },
    }),
})
