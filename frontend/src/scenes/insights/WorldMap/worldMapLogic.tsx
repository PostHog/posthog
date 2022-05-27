import { kea } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, TrendResult } from '~/types'
import { keyForInsightLogicProps } from '../sharedUtils'
import type { worldMapLogicType } from './worldMapLogicType'

export const worldMapLogic = kea<worldMapLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['scenes', 'insights', 'WorldMap', 'worldMapLogic', key],
    connect: {
        values: [insightLogic, ['insight', 'filters']],
    },
    actions: {
        showTooltip: (countryCode: string, countrySeries: TrendResult | null) => ({ countryCode, countrySeries }),
        hideTooltip: true,
        updateTooltipCoordinates: (x: number, y: number) => ({ x, y }),
    },
    reducers: {
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
    },
    selectors: {
        countryCodeToSeries: [
            (s) => [s.insight],
            (insight): Record<string, TrendResult> =>
                Object.fromEntries(
                    Array.isArray(insight.result)
                        ? insight.result.map((series: TrendResult) => [series.breakdown_value, series])
                        : []
                ),
        ],
        maxAggregatedValue: [
            (s) => [s.insight],
            (insight) =>
                Array.isArray(insight.result)
                    ? Math.max(...insight.result.map((series: TrendResult) => series.aggregated_value))
                    : 0,
        ],
    },
})
