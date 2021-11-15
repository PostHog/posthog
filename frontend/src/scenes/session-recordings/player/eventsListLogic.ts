import { kea } from 'kea'
import Grid from 'react-virtualized/dist/commonjs/Grid'
import { EventType, RecordingEventsFilters } from '~/types'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventsListLogicType } from './eventsListLogicType'
import { clamp, colonDelimitedDuration, findLastIndex, floorOrCeilMsToClosestSecond } from 'lib/utils'
import { CellMeasurerCache } from 'react-virtualized/dist/commonjs/CellMeasurer'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { RenderedRows } from 'react-virtualized/dist/commonjs/List'

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
        setGrid: (grid: Grid) => ({ grid }),
        clearCellCache: true,
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
        grid: [
            null as Grid | null,
            {
                setGrid: (_, { grid }) => grid,
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
        currentEventsIndices: [
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
            (selectors) => [selectors.currentEventsIndices, selectors.listEvents],
            (indices, events) => (index: number) =>
                (events?.[index]?.zeroOffsetTime ?? 0) >= indices.start &&
                (events?.[index]?.zeroOffsetTime ?? 0) < indices.end,
        ],
        currentEventsBoxSizeAndPosition: [
            (selectors) => [selectors.listEvents, selectors.isEventCurrent, selectors.grid],
            (events, isEventCurrent, grid) => {
                const firstEventIndex = events.findIndex((_, i) => isEventCurrent(i))
                const lastEventIndex = findLastIndex(events, (_, i) => isEventCurrent(i))

                if (
                    !grid ||
                    firstEventIndex >= grid.props.rowCount ||
                    lastEventIndex > grid.props.rowCount ||
                    (firstEventIndex < 1 && lastEventIndex < 1) ||
                    lastEventIndex < firstEventIndex
                ) {
                    return {
                        top: 0,
                        height: 0,
                    }
                }

                const gridState = grid.state as any
                const top =
                    gridState.instanceProps.rowSizeAndPositionManager.getSizeAndPositionOfCell(firstEventIndex).offset
                const lastEventSize =
                    gridState.instanceProps.rowSizeAndPositionManager.getSizeAndPositionOfCell(lastEventIndex)
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
