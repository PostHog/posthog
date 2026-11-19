import { useMemo } from 'react'

import type { MetricsChartSeries } from 'products/metrics/frontend/components/metricsSeries'
import { MetricsPanel } from 'products/metrics/frontend/panels/MetricsPanel'

import type { DataFrame } from './frame'

const DISPLAY = { type: 'bar' as const }

export function VolumeChart({ frames, height }: { frames: DataFrame[]; height: number }): JSX.Element {
    const series = useMemo<MetricsChartSeries[]>(
        () =>
            frames.map((frame, index) => {
                const times = frame.fields.find((field) => field.type === 'time')?.values ?? []
                const values = frame.fields.find((field) => field.type === 'number')?.values ?? []
                return {
                    labels: { series: frame.name ?? String(index + 1) },
                    points: times.map((time, point) => ({
                        time: new Date(Number(time)).toISOString(),
                        value: values[point] === null || values[point] === undefined ? null : Number(values[point]),
                    })),
                }
            }),
        [frames]
    )

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="relative flex shrink-0 flex-col" style={{ height }}>
            <MetricsPanel series={series} display={DISPLAY} fallbackName="Volume" />
        </div>
    )
}
