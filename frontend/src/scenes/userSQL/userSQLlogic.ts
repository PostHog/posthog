import { kea } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FilterType, InsightLogicProps } from '~/types'

import type { userSQLlogicType } from './userSQLlogicType'
export const userSQLlogic = kea<userSQLlogicType>({
    props: {} as InsightLogicProps,
    path: ['scenes', 'userSQL', 'userSQLlogic'],
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'insight', 'insightLoading', 'hiddenLegendKeys']],
    }),
    actions: () => ({
        setFilters: (filters: Partial<FilterType>, mergeFilters = true) => ({ filters, mergeFilters }),
    }),
    listeners: ({ values, props }) => ({
        setFilters: async ({ filters, mergeFilters }) => {
            insightLogic(props).actions.setFilters(mergeFilters ? { ...values.filters, ...filters } : filters)
        },
    }),
})
