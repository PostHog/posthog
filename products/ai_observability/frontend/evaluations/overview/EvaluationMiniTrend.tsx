import { Sparkline } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

// Fit the line to its own range so the shape shows. The number next to it carries the magnitude.
function paddedDomain(values: number[]): { min: number; max: number } | undefined {
    const finite = values.filter(Number.isFinite)
    if (finite.length === 0) {
        return undefined
    }
    const low = Math.min(...finite)
    const high = Math.max(...finite)
    const padding = high > low ? (high - low) * 0.2 : Math.max(Math.abs(high) * 0.05, 1)
    return { min: low - padding, max: high + padding }
}

export function EvaluationMiniTrend({ labels, values }: { labels: string[]; values: number[] }): JSX.Element {
    const theme = useChartTheme()
    return (
        <div className="h-7">
            <Sparkline data={values} labels={labels} theme={theme} height={28} valueDomain={paddedDomain(values)} />
        </div>
    )
}
