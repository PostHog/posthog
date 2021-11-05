import { kea } from 'kea'
import { smoothingFilterLogicType } from './smoothingFilterLogicType'
import { intervalFilterLogic } from '../IntervalFilter/intervalFilterLogic'
import { FilterType, InsightLogicProps, SmoothingType } from '~/types'
import { smoothingOptions } from './smoothings'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isTrendsInsight } from 'scenes/insights/sharedUtils'

export const smoothingFilterLogic = kea<smoothingFilterLogicType>({
    props: {} as InsightLogicProps,
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'insight']],
        actions: [intervalFilterLogic, ['setIntervalFilter']],
    }),
    // Have your own setSmoothing action that calls setFilters with the right params
    actions: () => ({
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setSmoothing: (filter: SmoothingType) => ({ filter }),
    }),
    reducers: {
        smoothing: [
            1 as SmoothingType,
            {
                setSmoothing: (_, { filter }) => filter,
            },
        ],
    },
    listeners: ({ actions, values, props }) => ({
        setSmoothing: async ({ filter }) => {
            insightLogic(props).actions.setFilters({ smoothing_intervals: filter })
        },
        setIntervalFilter: ({ filter }) => {
            if (filter === null) {
                return
            }
            if (!smoothingOptions[filter].find((option) => option.value === values.smoothing)) {
                actions.setSmoothing(1)
            }
        },
    }),
    // Use selectors to get the current value of the filter
    selectors: {
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<FilterType> => (isTrendsInsight(filters?.insight) ? filters ?? {} : {}),
        ],
    },
})
