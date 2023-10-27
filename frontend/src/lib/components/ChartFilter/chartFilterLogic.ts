import { kea, props, key, path, connect, actions, selectors, listeners } from 'kea'
import type { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export const chartFilterLogic = kea<chartFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['lib', 'components', 'ChartFilter', 'chartFilterLogic', key]),
    connect((props: InsightLogicProps) => ({
        actions: [insightVizDataLogic(props), ['updateInsightFilter', 'updateBreakdown']],
        values: [insightVizDataLogic(props), ['isTrends', 'isStickiness', 'display', 'series']],
    })),
    actions(() => ({
        setChartFilter: (chartFilter: ChartDisplayType) => ({ chartFilter }),
    })),
    selectors({
        chartFilter: [(s) => [s.display], (display): ChartDisplayType | null | undefined => display],
    }),
    listeners(({ actions, values }) => ({
        setChartFilter: ({ chartFilter }) => {
            const { isTrends, isStickiness, display, series } = values
            const newDisplay = chartFilter as ChartDisplayType

            if ((isTrends || isStickiness) && display !== newDisplay) {
                actions.updateInsightFilter({ display: newDisplay })

                // For the map, make sure we are breaking down by country
                if (isTrends && newDisplay === ChartDisplayType.WorldMap) {
                    const math = series?.[0].math

                    actions.updateBreakdown({
                        breakdown: '$geoip_country_code',
                        breakdown_type: ['dau', 'weekly_active', 'monthly_active'].includes(math || '')
                            ? 'person'
                            : 'event',
                    })
                }
            }
        },
    })),
])
