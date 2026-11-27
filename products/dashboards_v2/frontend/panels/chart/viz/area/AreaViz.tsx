import { useMemo } from 'react'

import { TimeSeriesComboChart, type TimeSeriesComboChartConfig } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { useTimeSeriesChart, useZoomToTimeRange } from '../../data/useTimeSeriesChart'
import type { NoOptions } from '../../vizTypes'

export function AreaViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { labels, series, baseConfig } = useTimeSeriesChart(frames)
    const config = useMemo(
        (): TimeSeriesComboChartConfig => ({ ...baseConfig, defaultSeriesType: 'area' }),
        [baseConfig]
    )
    const onDateRangeZoom = useZoomToTimeRange(labels, frames[0]?.meta?.interval)
    // A drag on the plot zooms, so it must not also move a headerless tile.
    return (
        <div className={onDateRangeZoom ? 'TileGrid__zoomable contents' : 'contents'}>
            <TimeSeriesComboChart series={series} labels={labels} config={config} onDateRangeZoom={onDateRangeZoom} />
        </div>
    )
}
