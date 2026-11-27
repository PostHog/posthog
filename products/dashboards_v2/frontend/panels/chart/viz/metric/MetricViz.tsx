import { useResolvedChartTheme } from '@posthog/quill-charts'
import { Metric, MetricDelta, MetricSparkline, MetricSubtitle, MetricValue } from '@posthog/quill-components/metric'

import type { DataFrame } from '../../../../query/queryTypes'
import { latestValue } from '../../data/frameShapes'
import { timeSeriesFromFrames } from '../../data/timeSeriesFrames'
import type { MetricOptions } from './metricSpec'

const FORMATTERS: Record<NonNullable<MetricOptions['format']>, (value: number) => string> = {
    number: (value) => value.toLocaleString(undefined, { maximumFractionDigits: 2 }),
    currency: (value) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD' }),
    percentage: (value) => `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`,
}

/** The latest value of the first frame as a metric card, over a sparkline of the whole range when the frame has timestamps. */
export function MetricViz({ frames, options }: { frames: DataFrame[]; options: MetricOptions }): JSX.Element {
    const theme = useResolvedChartTheme()
    const first = frames.slice(0, 1)
    const latest = latestValue(first)
    if (latest === null) {
        return <span className="text-2xl font-semibold">-</span>
    }
    const { labels, series } = timeSeriesFromFrames(first)
    const data = series[0]?.data.filter(Number.isFinite) ?? []
    const trend = data.length > 1
    return (
        <Metric
            value={latest}
            data={trend ? data : undefined}
            labels={trend ? labels.filter((_, index) => Number.isFinite(series[0].data[index])) : undefined}
            formatValue={FORMATTERS[options.format ?? 'number']}
            theme={theme}
            sparklineFill
            // The tile already pads its content, so the card's own padding would inset the number past the title.
            className="flex min-h-0 w-full flex-1 flex-col px-0"
        >
            <div className="flex items-center gap-2">
                <MetricValue />
                {trend && <MetricDelta />}
            </div>
            {trend && <MetricSubtitle className="mt-1" />}
            {trend && <MetricSparkline className="mt-2 min-h-0 flex-1" />}
        </Metric>
    )
}
