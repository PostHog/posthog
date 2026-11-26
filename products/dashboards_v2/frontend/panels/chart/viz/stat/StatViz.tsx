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

/** The latest value of the first frame, over a sparkline of the whole range when the frame has timestamps. */
export function StatViz({ frames, options }: { frames: DataFrame[]; options: StatOptions }): JSX.Element {
    const theme = useChartTheme()
    const first = frames.slice(0, 1)
    const hasTime = first.some((frame) => frame.fields.some((field) => field.type === 'time'))
    const { labels, series } = timeSeriesFromFrames(first)
    const numbers = first[0]?.fields.find((field) => field.type === 'number')?.values ?? []
    const latest = numbers.findLast((value): value is number => typeof value === 'number' && Number.isFinite(value))
    return (
        <div className="flex min-h-0 w-full flex-1 flex-col">
            <span className="text-2xl font-semibold tabular-nums">
                {latest === undefined ? '-' : FORMATTERS[options.format ?? 'number'](latest)}
            </span>
            {hasTime && (
                <div className="flex min-h-0 flex-1 flex-col">
                    <Sparkline data={series[0]?.data ?? []} labels={labels} theme={theme} fill />
                </div>
            )}
        </div>
    )
}
