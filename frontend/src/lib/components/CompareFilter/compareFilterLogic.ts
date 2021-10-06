import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import { ViewType } from '~/types'
import { compareFilterLogicType } from './compareFilterLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'

interface CompareFilterLogicProps {
    dashboardItemId?: number
}

export const compareFilterLogic = kea<compareFilterLogicType<CompareFilterLogicProps>>({
    props: {} as CompareFilterLogicProps,
    key: (props) => props.dashboardItemId || 'new',
    connect: (props: CompareFilterLogicProps) => ({
        values: [insightLogic({ id: props.dashboardItemId }), ['filters']],
        actions: [insightLogic({ id: props.dashboardItemId }), ['updateInsightFilters']],
    }),
    actions: () => ({
        setCompare: (compare: boolean) => ({ compare }),
        setDisabled: (disabled: boolean) => ({ disabled }),
        toggleCompare: true,
    }),
    selectors: {
        compare: [(s) => [s.filters], (filters) => !!filters.compare],
        disabled: [
            (s) => [s.filters],
            ({ insight, date_from }) => insight === ViewType.LIFECYCLE || date_from === 'all',
        ],
    },
    reducers: () => ({
        disabled: [
            false,
            {
                setDisabled: (_, { disabled }) => disabled,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        setCompare: ({ compare }) => {
            if (!objectsEqual(compare, values.compare)) {
                actions.updateInsightFilters({ ...values.filters, compare })
            }
        },
        toggleCompare: () => {
            actions.setCompare(!values.compare)
        },
    }),
})
