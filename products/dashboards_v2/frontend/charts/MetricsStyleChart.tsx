import { useMemo } from 'react'

import type { MetricsChartSeries } from 'products/metrics/frontend/components/metricsSeries'
import { MetricsPanel } from 'products/metrics/frontend/panels/MetricsPanel'

import type { Panel } from '../spec'
import { metricsDisplayOf } from './displaySettings'
import { EmptyData } from './EmptyData'

export function MetricsStyleChart({ panel, series }: { panel: Panel; series: MetricsChartSeries[] }): JSX.Element {
    const display = useMemo(() => metricsDisplayOf(panel), [panel])

    if (!series.some((item) => item.points.length)) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col">
            <MetricsPanel series={series} display={display} fallbackName={panel.title || 'Value'} />
        </div>
    )
}
