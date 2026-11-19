import { useMemo } from 'react'

import { BoxPlot, type BoxPlotDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { Panel } from '../spec'
import { EmptyData } from './EmptyData'

interface BoxPlotChartProps {
    panel: Panel
    labels: string[]
    boxes: BoxPlotDatum[]
}

export function BoxPlotChart({ panel, labels, boxes }: BoxPlotChartProps): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo(() => [{ key: 'spread', label: panel.title || 'Value', data: boxes }], [boxes, panel.title])

    if (!boxes.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col">
            <BoxPlot className="min-h-0 flex-1" theme={theme} labels={labels} series={series} />
        </div>
    )
}
