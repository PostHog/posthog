import { useMemo } from 'react'

import { PieChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { formatMetricValue } from 'products/metrics/frontend/panels/metricsUnits'

import type { Panel } from '../spec'
import { unitOf } from './displaySettings'
import { EmptyData } from './EmptyData'
import type { PanelCategory } from './panelData'

export function CategoryPieChart({ panel, categories }: { panel: Panel; categories: PanelCategory[] }): JSX.Element {
    const theme = useChartTheme()
    const unit = unitOf(panel)
    const series = useMemo(
        () =>
            categories.map((category, index) => ({
                key: String(index),
                label: category.label,
                data: [category.value],
            })),
        [categories]
    )

    if (!categories.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col">
            <PieChart
                className="min-h-0 flex-1"
                theme={theme}
                series={series}
                valueFormatter={(value: number) => formatMetricValue(value, unit)}
                config={{
                    innerRadiusRatio: panel.viz.options?.donut === false ? 0 : 0.6,
                    showLabelOnSlice: false,
                    showValueOnSlice: true,
                    isPercent: true,
                    legend: { show: true, position: 'right' },
                }}
            />
        </div>
    )
}
