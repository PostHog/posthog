import { useMemo } from 'react'

import { TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { useTimeSeriesChart } from '../../data/useTimeSeriesChart'
import type { NoOptions } from '../../vizTypes'

export function LineViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { labels, series, multiTarget, baseConfig } = useTimeSeriesChart(frames)
    const severalTargets = useMemo(() => new Set(frames.map((frame) => frame.refId)).size > 1, [frames])
    const config = useMemo(
        (): TimeSeriesLineChartConfig => ({
            ...baseConfig,
            // Targets in other languages sample on their own steps, so a series is drawn across the others' points.
            connectNulls: severalTargets,
            // Their merged timestamps are unevenly spaced, so each point sits at its time rather than its index.
            ...(multiTarget ? { xScale: 'time' as const } : {}),
        }),
        [baseConfig, multiTarget, severalTargets]
    )
    return <TimeSeriesLineChart series={series} labels={labels} config={config} />
}
