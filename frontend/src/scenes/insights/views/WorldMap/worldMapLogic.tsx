import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightLogicProps, TrendResult } from '~/types'

import { keyForInsightLogicProps } from '../../sharedUtils'
import type { worldMapLogicType } from './worldMapLogicType'

export const worldMapLogic = kea<worldMapLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'WorldMap', 'worldMapLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['insightData', 'trendsFilter', 'breakdownFilter', 'series', 'querySource', 'theme'],
        ],
    })),
    actions({
        showTooltip: (countryCode: string, countrySeries: TrendResult | null) => ({ countryCode, countrySeries }),
        hideTooltip: true,
        updateTooltipCoordinates: (x: number, y: number) => ({ x, y }),
    }),
    reducers({
        isTooltipShown: [
            false,
            {
                showTooltip: () => true,
                hideTooltip: () => false,
            },
        ],
        currentTooltip: [
            null as [string, TrendResult | null] | null,
            {
                showTooltip: (_, { countryCode, countrySeries }) => [countryCode, countrySeries],
            },
        ],
        tooltipCoordinates: [
            null as [number, number] | null,
            {
                updateTooltipCoordinates: (_, { x, y }) => [x, y],
            },
        ],
    }),
    selectors({
        countryCodeToSeries: [
            (s) => [s.insightData],
            (insightData): Record<string, TrendResult> =>
                Object.fromEntries(
                    Array.isArray(insightData?.result)
                        ? (insightData?.result as TrendResult[]).map((series) => [series.breakdown_value, series])
                        : []
                ),
        ],
        maxAggregatedValue: [
            (s) => [s.insightData],
            (insightData) =>
                Array.isArray(insightData?.result)
                    ? Math.max(...(insightData?.result as TrendResult[]).map((series) => series.aggregated_value))
                    : 0,
        ],
    }),
])
