import { useMemo } from 'react'

import { LineChart, type LineChartConfig, ReferenceLine, type Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

// Illustrative only: no data exists yet, so the line shows the direction the goal moves in.
const BASELINE = [52, 50, 54, 48, 51, 47, 49, 50]
const LABELS = BASELINE.map((_, index) => `week-${index}`)
const START = 50

export function GoalChart({
    direction,
    target,
    metric,
}: {
    direction: 'Increase' | 'Reduce'
    target: number
    metric: string
}): JSX.Element {
    const theme = useChartTheme()
    const goal = START * (1 + ((direction === 'Increase' ? 1 : -1) * Math.min(target, 90)) / 100)
    const series = useMemo<Series[]>(() => [{ key: 'baseline', label: metric, data: BASELINE }], [metric])
    const config = useMemo<LineChartConfig>(
        () => ({
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showCrosshair: false,
            curve: 'monotone',
            tooltip: { enabled: false },
            valueDomain: { min: Math.min(goal, 45) - 5, max: Math.max(goal, 55) + 5 },
        }),
        [goal]
    )

    return (
        <div className="flex h-24 flex-col pointer-events-none" aria-hidden>
            <LineChart series={series} labels={LABELS} theme={theme} config={config}>
                <ReferenceLine value={goal} orientation="horizontal" variant="goal" label="Target" />
            </LineChart>
        </div>
    )
}
