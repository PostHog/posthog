import { useMemo } from 'react'

import { BarChart } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { ScoreHistogramApi } from '../../generated/api.schemas'

export function EvaluationScoreHistogram({ histogram }: { histogram: ScoreHistogramApi }): JSX.Element {
    const theme = useChartTheme()
    const labels = useMemo(() => histogram.buckets.map((bucket) => bucket.label), [histogram])
    const series = useMemo<Series[]>(
        () => [{ key: 'results', label: 'Results', data: histogram.buckets.map((bucket) => bucket.count) }],
        [histogram]
    )
    return (
        <div className="h-48 min-w-0 flex flex-col">
            <BarChart
                series={series}
                labels={labels}
                theme={theme}
                config={{ showGrid: true, barCornerRadius: 2, xAxisLabel: 'Score', yAxisLabel: 'Results' }}
            />
        </div>
    )
}
