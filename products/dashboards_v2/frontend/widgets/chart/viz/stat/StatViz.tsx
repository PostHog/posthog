import { Sparkline } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { timeSeriesFromFrames } from '../../timeSeriesFrames'
import type { DataFrame } from '../../vizTypes'
import type { StatOptions } from './statSpec'

const FORMATTERS: Record<NonNullable<StatOptions['format']>, (value: number) => string> = {
    number: (value) => value.toLocaleString(undefined, { maximumFractionDigits: 2 }),
    currency: (value) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD' }),
    percentage: (value) => `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`,
}

/** The latest value of the first series, over a sparkline of the whole range. */
export function StatViz({ frames, options }: { frames: DataFrame[]; options: StatOptions }): JSX.Element {
    const theme = useChartTheme()
    const { labels, series } = timeSeriesFromFrames(frames.slice(0, 1))
    const data = series[0]?.data ?? []
    const latest = data.findLast((value) => Number.isFinite(value))
    return (
        <div className="flex min-h-0 w-full flex-1 flex-col">
            <span className="text-2xl font-semibold tabular-nums">
                {latest === undefined ? '-' : FORMATTERS[options.format ?? 'number'](latest)}
            </span>
            <div className="flex min-h-0 flex-1 flex-col">
                <Sparkline data={data} labels={labels} theme={theme} fill />
            </div>
        </div>
    )
}
