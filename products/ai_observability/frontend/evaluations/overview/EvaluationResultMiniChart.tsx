import { useMemo } from 'react'

import { ProportionBar, Sparkline } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { toChartValues } from './evaluationOverviewDisplay'

const SENTIMENT_COLORS = { positive: 'success', neutral: 'muted', negative: 'danger' } as const

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

export function EvaluationResultMiniChart({
    row,
    buckets,
}: {
    row: EvaluationResultApi
    buckets: string[]
}): JSX.Element {
    const theme = useChartTheme()
    const { summary } = row

    const parts = useMemo<Series[] | null>(() => {
        if (summary.kind === 'sentiment') {
            return (['positive', 'neutral', 'negative'] as const).map((key) => ({
                key,
                label: key[0].toUpperCase() + key.slice(1),
                data: [summary[key]],
                color: getColorVar(SENTIMENT_COLORS[key]),
            }))
        }
        // Labels on a multiple-selection result overlap, so a part-of-whole bar would mislead.
        if (summary.kind === 'categories' && !summary.multiple) {
            return summary.categories.map((category) => ({
                key: category.key,
                label: category.label,
                data: [category.count],
            }))
        }
        return null
    }, [summary])
    const values = useMemo(() => toChartValues(row.trend.values), [row])

    if (parts) {
        return (
            <div className="h-7 flex flex-col justify-center">
                <ProportionBar
                    series={parts}
                    theme={theme}
                    config={{ barHeight: 8, barCornerRadius: 2, legend: { show: false } }}
                />
            </div>
        )
    }
    return (
        <div className="h-7">
            <Sparkline data={values} labels={buckets} theme={theme} height={28} valueDomain={paddedDomain(values)} />
        </div>
    )
}
