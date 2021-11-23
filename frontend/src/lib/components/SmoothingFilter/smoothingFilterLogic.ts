import { kea } from 'kea'
import { smoothingFilterLogicType } from './smoothingFilterLogicType'
import { InsightLogicProps, SmoothingType } from '~/types'
import { smoothingOptions } from './smoothings'
import { insightLogic } from 'scenes/insights/insightLogic'

export const smoothingFilterLogic = kea<smoothingFilterLogicType>({
    path: ['lib', 'components', 'SmoothingFilter', 'smoothingFilterLogic'],
    props: {} as InsightLogicProps,
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters']],
        actions: [insightLogic(props), ['setFilters']],
    }),
    actions: () => ({
        setSmoothing: (filter: SmoothingType) => ({ filter }),
    }),
    listeners: ({ actions, values }) => ({
        setSmoothing: async ({ filter }) => {
            actions.setFilters({
                ...values.filters,
                smoothing_intervals: filter,
            })
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
