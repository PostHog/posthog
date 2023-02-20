import { kea, props, key, path, connect, actions, selectors, listeners } from 'kea'
import { objectsEqual } from 'lib/utils'
import { ChartDisplayType, InsightLogicProps, TrendsFilterType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { TrendsFilter } from '~/queries/schema'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { filterForQuery } from '~/queries/utils'

import type { showValueFilterLogicType } from './showValueFilterLogicType'

export const showValueFilterLogic = kea<showValueFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['lib', 'components', 'ShowValueFilter', 'showValueFilterLogic', key]),
    connect((props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters'], insightDataLogic(props), ['updateInsightFilter']],
        values: [
            insightLogic(props),
            ['filters as inflightFilters', 'canEditInsight'],
            insightDataLogic(props),
            ['querySource'],
        ],
    })),

    actions(() => ({
        setShowValue: (showValue: boolean) => ({ showValue }),
        toggleShowValue: true,
    })),

    selectors({
        filters: [
            (s) => [s.inflightFilters],
            (inflightFilters): Partial<TrendsFilterType> =>
                inflightFilters && isTrendsFilter(inflightFilters) ? inflightFilters : {},
        ],
        showValue: [
            (s) => [s.filters],
            (filters) => filters && isTrendsFilter(filters) && !!filters.show_values_on_series,
        ],
        disabled: [
            (s) => [s.filters, s.canEditInsight],
            (filters, canEditInsight) =>
                !canEditInsight ||
                !isTrendsFilter(filters) ||
                (filters.display &&
                    [ChartDisplayType.WorldMap, ChartDisplayType.BoldNumber, ChartDisplayType.ActionsTable].includes(
                        filters.display
                    )),
        ],
    }),

    listeners(({ values, actions }) => ({
        setShowValue: ({ showValue }) => {
            if (!objectsEqual(showValue, values.showValue)) {
                const newFilters: Partial<TrendsFilterType> = { ...values.filters, show_values_on_series: showValue }
                actions.setFilters(newFilters)
            }

            const currentShowValue = (filterForQuery(values.querySource) as TrendsFilter | undefined)
                ?.show_values_on_series
            if (currentShowValue !== showValue) {
                actions.updateInsightFilter({ show_values_on_series: showValue })
            }
        },
        toggleShowValue: () => {
            actions.setShowValue(!values.showValue)
        },
    })),
])
