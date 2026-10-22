import { useMemo } from 'react'

import { ProportionBar } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { EvaluationMiniTrend } from './EvaluationMiniTrend'
import { toChartValues } from './evaluationOverviewDisplay'

const SENTIMENT_COLORS = { positive: 'success', neutral: 'muted', negative: 'danger' } as const

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
    return <EvaluationMiniTrend labels={buckets} values={values} />
}
