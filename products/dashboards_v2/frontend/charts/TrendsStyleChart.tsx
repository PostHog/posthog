import { useValues } from 'kea'
import { useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getSeriesColor } from 'lib/colors'
import { teamLogic } from 'scenes/teamLogic'

import {
    buildTrendsLineTimeSeriesConfig,
    buildTrendsSeries,
    type TrendsResultLike,
} from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

import type { Panel } from '../spec'
import { EmptyData } from './EmptyData'

const HOUR_MS = 3_600_000

function intervalOf(days: string[]): 'hour' | 'day' | 'week' | 'month' {
    const step = days.length > 1 ? new Date(days[1]).getTime() - new Date(days[0]).getTime() : 24 * HOUR_MS
    if (step < 24 * HOUR_MS) {
        return 'hour'
    }
    if (step < 7 * 24 * HOUR_MS) {
        return 'day'
    }
    return step < 28 * 24 * HOUR_MS ? 'week' : 'month'
}

interface TrendsStyleChartProps {
    panel: Panel
    results: TrendsResultLike[]
    timezone?: string
}

export function TrendsStyleChart({ panel, results, timezone: panelTimezone }: TrendsStyleChartProps): JSX.Element {
    const theme = useChartTheme()
    const { timezone: projectTimezone } = useValues(teamLogic)
    const timezone = panelTimezone ?? projectTimezone
    const isArea = !!panel.viz.options?.area
    const days = results[0]?.days
    const labels = useMemo(() => days ?? [], [days])

    const series = useMemo(
        () => buildTrendsSeries(results, { isArea, getColor: (_, index) => getSeriesColor(index) }),
        [results, isArea]
    )
    const config = useMemo(
        () =>
            buildTrendsLineTimeSeriesConfig({
                results,
                isPercentStackView: false,
                interval: intervalOf(labels),
                timezone,
                allDays: labels,
                yAxisMin: panel.fieldConfig?.min,
                yAxisMax: panel.fieldConfig?.max,
            }),
        [results, labels, timezone, panel.fieldConfig?.min, panel.fieldConfig?.max]
    )

    if (!labels.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col">
            <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
