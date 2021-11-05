import { kea } from 'kea'
import { smoothingFilterLogicType } from './smoothingFilterLogicType'
import { FilterType, InsightLogicProps, SmoothingType } from '~/types'
import { smoothingOptions } from './smoothings'
import { insightLogic } from 'scenes/insights/insightLogic'

export const smoothingFilterLogic = kea<smoothingFilterLogicType>({
    props: {} as InsightLogicProps,
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'insight']],
    }),
    // Have your own setSmoothing action that calls setFilters with the right params
    actions: () => ({
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setSmoothing: (filter: SmoothingType) => ({ filter }),
    }),
    listeners: ({ actions, props }) => ({
        setSmoothing: async ({ filter }) => {
            insightLogic(props).actions.setFilters({ smoothing_intervals: filter })
        },
        setFilters: ({ filters: { interval, smoothing_intervals } }) => {
            if (!interval) {
                return
            }
            if (!smoothingOptions[interval].find((option) => option.value === smoothing_intervals)) {
                if (smoothing_intervals !== 1) {
                    actions.setSmoothing(1)
                }
            }
        },
    }),
})
