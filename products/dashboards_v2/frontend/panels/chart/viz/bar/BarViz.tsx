import { useMemo } from 'react'

import { TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { useTimeSeriesChart } from '../../data/useTimeSeriesChart'
import type { BarOptions } from './barSpec'

export function BarViz({ frames, options }: { frames: DataFrame[]; options: BarOptions }): JSX.Element {
    const { labels, series, baseConfig } = useTimeSeriesChart(frames)
    const stacked = !!options.stack
    const config = useMemo(
        (): TimeSeriesBarChartConfig => ({ ...baseConfig, barLayout: stacked ? 'stacked' : 'grouped' }),
        [baseConfig, stacked]
    )
    return <TimeSeriesBarChart series={series} labels={labels} config={config} />
}
