import { useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getSeriesColor } from 'lib/colors'

import {
    buildRetentionChartModel,
    type RetentionCohortLike,
} from 'products/product_analytics/frontend/insights/retention/shared/retentionChartTransforms'

import { EmptyData } from './EmptyData'

export function RetentionChart({ cohorts }: { cohorts: RetentionCohortLike[] }): JSX.Element {
    const theme = useChartTheme()
    const { series, labels, lineConfig } = useMemo(
        () =>
            buildRetentionChartModel(cohorts, {
                aggregationType: 'count',
                reference: 'total',
                period: 'Week',
                getColor: getSeriesColor,
            }),
        [cohorts]
    )

    if (!series.length || !labels.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col" data-attr="dashboard-v2-retention-chart">
            <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={lineConfig} />
        </div>
    )
}
