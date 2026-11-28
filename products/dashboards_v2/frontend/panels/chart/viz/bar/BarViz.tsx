import { useMemo } from 'react'

import { TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { useTimeSeriesChart, useZoomToTimeRange } from '../../data/useTimeSeriesChart'
import type { BarOptions } from './barSpec'

export function BarViz({ frames, options }: { frames: DataFrame[]; options: BarOptions }): JSX.Element {
    const { labels, series, baseConfig } = useTimeSeriesChart(frames)
    const stacked = !!options.stack
    const config = useMemo(
        (): TimeSeriesBarChartConfig => ({ ...baseConfig, barLayout: stacked ? 'stacked' : 'grouped' }),
        [baseConfig, stacked]
    )
    const onDateRangeZoom = useZoomToTimeRange(labels, frames[0]?.meta?.interval)
    // A drag on the plot zooms, so it must not also move a headerless tile.
    return (
        <div className={onDateRangeZoom ? 'TileGrid__zoomable contents' : 'contents'}>
            <TimeSeriesBarChart series={series} labels={labels} config={config} onDateRangeZoom={onDateRangeZoom} />
        </div>
    )
}
