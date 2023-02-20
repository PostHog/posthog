import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import { InsightLogicProps, InsightType, TrendsFilterType } from '~/types'
import { isFunnelsFilter, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { FunnelsFilter, TrendsFilter } from '~/queries/schema'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { filterForQuery } from '~/queries/utils'

import type { showValueFilterLogicType } from './showValueFilterLogicType'

export const showValueFilterLogic = kea<showValueFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'ShowValueFilter', 'showValueFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters'], insightDataLogic(props), ['updateInsightFilter']],
        values: [
            insightLogic(props),
            ['filters as inflightFilters', 'canEditInsight'],
            insightDataLogic(props),
            ['querySource'],
        ],
    }),

    actions: () => ({
        setShowValue: (showValue: boolean) => ({ showValue }),
        toggleShowValue: true,
    }),

    selectors: {
        filters: [
            (s) => [s.inflightFilters],
            (inflightFilters): Partial<TrendsFilterType> =>
                inflightFilters && (isTrendsFilter(inflightFilters) || isFunnelsFilter(inflightFilters))
                    ? inflightFilters
                    : {},
        ],
        showValue: [
            (s) => [s.filters],
            (filters) =>
                filters && (isTrendsFilter(filters) || isFunnelsFilter(filters)) && !!filters.show_values_on_series,
        ],
        disabled: [
            (s) => [s.filters, s.canEditInsight],
            ({ insight }, canEditInsight) =>
                !canEditInsight || (!!insight && ![InsightType.TRENDS, InsightType.FUNNELS].includes(insight)),
        ],
    },

    listeners: ({ values, actions }) => ({
        setShowValue: ({ showValue }) => {
            if (!objectsEqual(showValue, values.showValue)) {
                const newFilters: Partial<TrendsFilterType> = { ...values.filters, show_values_on_series: showValue }
                console.log('setting filter in filter logic', newFilters)
                actions.setFilters(newFilters)
            }

            const currentShowValue = (filterForQuery(values.querySource) as TrendsFilter | FunnelsFilter | undefined)
                ?.show_values_on_series
            if (currentShowValue !== showValue) {
                actions.updateInsightFilter({ show_values_on_series: showValue })
            }
        },
        toggleShowValue: () => {
            actions.setShowValue(!values.showValue)
        },
    }),
})
