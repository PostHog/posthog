import { useMemo } from 'react'

import { BarChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getSeriesColor } from 'lib/colors'

import {
    buildFunnelStepsBarConfig,
    buildSingleSeriesFunnelStepsBars,
} from 'products/product_analytics/frontend/insights/funnels/shared/funnelStepsBarShared'

import { EmptyData } from './EmptyData'
import type { PanelFunnelStep } from './panelData'

const CONFIG = buildFunnelStepsBarConfig({ maxCategoryLabelWidth: 120, tooltipPlacement: 'cursor' })

export function FunnelStepsChart({ steps }: { steps: PanelFunnelStep[] }): JSX.Element {
    const theme = useChartTheme()
    const { series, labels, rows } = useMemo(
        () => buildSingleSeriesFunnelStepsBars(steps, { color: getSeriesColor(0) }),
        [steps]
    )
    const config = useMemo(
        () => ({ ...CONFIG, xTickFormatter: (_value: string | number, index: number) => rows[index]?.name ?? '' }),
        [rows]
    )

    if (!steps.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col" data-attr="dashboard-v2-funnel-chart">
            <BarChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
