import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightLogicProps, TrendResult } from '~/types'

import { keyForInsightLogicProps } from '../../sharedUtils'
import type { regionMapLogicType } from './regionMapLogicType'

const getTrendResults = (insightData: Record<string, any> | null | undefined): TrendResult[] =>
    Array.isArray(insightData?.result) ? (insightData.result as TrendResult[]) : []

const getSeriesValue = (series: TrendResult | null | undefined): number =>
    series?.aggregated_value ?? series?.count ?? 0

export const regionMapLogic = kea<regionMapLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'RegionMap', 'regionMapLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['insightData', 'trendsFilter', 'breakdownFilter', 'series', 'querySource', 'theme'],
        ],
    })),
    actions({
        showTooltip: (
            regionCode: string,
            regionName: string,
            countryCode: string,
            regionSeries: TrendResult | null
        ) => ({ regionCode, regionName, countryCode, regionSeries }),
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
            null as [string, string, string, TrendResult | null] | null,
            {
                showTooltip: (_, { regionCode, regionName, countryCode, regionSeries }) => [
                    regionCode,
                    regionName,
                    countryCode,
                    regionSeries,
                ],
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
        subdivisionCodeToSeries: [
            (s) => [s.insightData],
            (insightData): Record<string, TrendResult> => {
                const results = getTrendResults(insightData)
                if (results.length === 0) {
                    return {}
                }
                return Object.fromEntries(
                    results
                        .filter((series) => {
                            const breakdown = series.breakdown_value
                            return Array.isArray(breakdown) && breakdown[0] && breakdown[1]
                        })
                        .map((series) => {
                            const breakdown = series.breakdown_value as string[]
                            const iso3166_2 = `${breakdown[0]}-${breakdown[1]}`
                            return [iso3166_2, series]
                        })
                )
            },
        ],
        maxAggregatedValue: [
            (s) => [s.insightData],
            (insightData) => {
                return getTrendResults(insightData).reduce((max, series) => Math.max(max, getSeriesValue(series)), 0)
            },
        ],
    }),
])
