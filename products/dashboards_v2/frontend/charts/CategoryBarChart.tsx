import { useMemo } from 'react'

import { BarChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { formatMetricValue } from 'products/metrics/frontend/panels/metricsUnits'

import type { Panel } from '../spec'
import { unitOf } from './displaySettings'
import { EmptyData } from './EmptyData'
import type { PanelCategory } from './panelData'

export function CategoryBarChart({ panel, categories }: { panel: Panel; categories: PanelCategory[] }): JSX.Element {
    const theme = useChartTheme()
    const unit = unitOf(panel)
    const labels = useMemo(() => categories.map((category) => category.label), [categories])
    const series = useMemo(
        () => [{ key: 'value', label: panel.title || 'Value', data: categories.map((category) => category.value) }],
        [categories, panel.title]
    )

    if (!categories.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col">
            <BarChart
                className="min-h-0 flex-1"
                theme={theme}
                labels={labels}
                series={series}
                config={{
                    axisOrientation: panel.viz.options?.horizontal ? 'horizontal' : 'vertical',
                    showGrid: true,
                    yTickFormatter: (value: number) => formatMetricValue(value, unit),
                    tooltip: { valueFormatter: (value: number) => formatMetricValue(value, unit) },
                    legend: { show: false },
                }}
            />
        </div>
    )
}
