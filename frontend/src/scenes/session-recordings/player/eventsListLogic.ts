import { kea } from 'kea'
import { EventType, RecordingEventsFilters } from '~/types'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventsListLogicType } from './eventsListLogicType'
import { colonDelimitedDuration } from 'lib/utils'
import { CellMeasurerCache } from 'react-virtualized/dist/commonjs/CellMeasurer'

export const eventsListLogic = kea<eventsListLogicType>({
    connect: {
        actions: [sessionRecordingLogic, ['setFilters']],
        values: [sessionRecordingLogic, ['eventsToShow']],
    },
    actions: {
        setLocalFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        clearCellCache: true,
    },
    reducers: {
        localFilters: [
            {} as Partial<RecordingEventsFilters>,
            {
                setLocalFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    },
    listeners: ({ cache, actions, values }) => ({
        setLocalFilters: async (_, breakpoint) => {
            await breakpoint(250)
            actions.setFilters(values.localFilters)
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
    }),
    events: ({ cache, actions }) => ({
        afterMount: () => {
            cache.cellMeasurerCache = new CellMeasurerCache({
                fixedWidth: true,
                defaultHeight: 50,
            })
            window.addEventListener('resize', actions.clearCellCache)
        },
        afterUnmount: () => {
            cache.cellMeasurerCache = null
            window.removeEventListener('resize', actions.clearCellCache)
        },
    }),
})
