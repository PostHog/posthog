import { useMemo } from 'react'

import { BarList } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { CategoriesSummaryApi, SentimentSummaryApi } from '../../generated/api.schemas'

export function EvaluationCategoryShares({
    summary,
    gradedCount,
}: {
    summary: CategoriesSummaryApi | SentimentSummaryApi
    gradedCount: number
}): JSX.Element {
    const theme = useChartTheme()

    const series = useMemo<Series[]>(() => {
        if (summary.kind === 'sentiment') {
            return [
                { key: 'negative', label: 'Negative', data: [summary.negative], color: getColorVar('danger') },
                { key: 'neutral', label: 'Neutral', data: [summary.neutral], color: getColorVar('muted') },
                { key: 'positive', label: 'Positive', data: [summary.positive], color: getColorVar('success') },
            ]
        }
        const rows: Series[] = summary.categories.map((category) => ({
            key: category.key,
            label: category.label,
            data: [category.count],
        }))
        if (summary.multiple) {
            rows.push({
                key: '__none',
                label: 'No categories',
                data: [summary.noCategoriesCount],
                color: getColorVar('muted'),
            })
        }
        return rows
    }, [summary])

    return (
        <div className="flex flex-col gap-2">
            <BarList
                series={series}
                theme={theme}
                total={gradedCount}
                valueFormatter={(value) =>
                    `${humanFriendlyNumber(value)} · ${gradedCount > 0 ? Math.round((value / gradedCount) * 100) : 0}%`
                }
            />
            {summary.kind === 'categories' && summary.multiple && (
                <div className="text-xs text-secondary">
                    One result can carry several labels, so shares can add up to more than 100%.
                </div>
            )}
        </div>
    )
}
