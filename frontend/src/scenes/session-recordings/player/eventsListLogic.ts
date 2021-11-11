import { kea } from 'kea'
import { EventType, RecordingEventsFilters } from '~/types'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventsListLogicType } from './eventsListLogicType'
import { clamp, colonDelimitedDuration } from 'lib/utils'
import { CellMeasurerCache } from 'react-virtualized/dist/commonjs/CellMeasurer'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { RenderedRows } from 'react-virtualized/dist/commonjs/List'

export const DEFAULT_ROW_HEIGHT = 50
export const OVERSCANNED_ROW_COUNT = 50

export const eventsListLogic = kea<eventsListLogicType>({
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
        currentEventStartIndex: [
            (selectors) => [selectors.listEvents, selectors.zeroOffsetTime],
            (events, time) => {
                return clamp(events.findIndex((e) => (e.zeroOffsetTime ?? 0) > time.current) - 1, 0, events.length - 1)
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
