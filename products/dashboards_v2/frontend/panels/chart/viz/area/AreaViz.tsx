import { useMemo } from 'react'

import { TimeSeriesComboChart, type TimeSeriesComboChartConfig } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { useTimeSeriesChart } from '../../data/useTimeSeriesChart'
import type { NoOptions } from '../../vizTypes'

export function AreaViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { labels, series, baseConfig } = useTimeSeriesChart(frames)
    const config = useMemo(
        (): TimeSeriesComboChartConfig => ({ ...baseConfig, defaultSeriesType: 'area' }),
        [baseConfig]
    )
    return <TimeSeriesComboChart series={series} labels={labels} config={config} />
}
