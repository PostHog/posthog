import { useMemo } from 'react'

import { ProportionBar } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { EvaluationResultApi, PassRateSummaryApi } from '../../generated/api.schemas'
import { formatPercent } from './evaluationOverviewDisplay'

export function EvaluationResultOutcomes({
    row,
    summary,
}: {
    row: EvaluationResultApi
    summary: PassRateSummaryApi
}): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () => [
            { key: 'passed', label: 'Passed', data: [summary.passed], color: getColorVar('success') },
            { key: 'failed', label: 'Failed', data: [summary.failed], color: getColorVar('danger') },
        ],
        [summary]
    )
    const total = summary.passed + summary.failed
    const outside = (
        [
            ['N/A', row.notApplicableCount],
            ['skipped', row.skippedCount],
        ] as [string, number][]
    ).filter(([, count]) => count > 0)

    return (
        <>
            {/* The bar's own legend sits in a scroll box a few pixels too short for its row, which shows an empty
                scrollbar where scrollbars always show, so this card draws the legend itself. */}
            <ProportionBar
                series={series}
                theme={theme}
                config={{ barHeight: 12, barCornerRadius: 3, legend: { show: false } }}
            />
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                {series.map((part) => (
                    <span key={part.key} className="inline-flex items-center gap-1.5">
                        <span
                            aria-hidden
                            className="inline-block size-2.5 rounded-sm shrink-0"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: part.color }}
                        />
                        <span>{part.label}</span>
                        <span className="text-secondary tabular-nums">{`${formatPercent(total > 0 ? (part.data[0] / total) * 100 : NaN)} · ${humanFriendlyNumber(part.data[0])}`}</span>
                    </span>
                ))}
            </div>
            <div className="text-xs text-secondary">
                {outside.length > 0
                    ? `Not in the rate: ${outside.map(([label, count]) => `${humanFriendlyNumber(count)} ${label}`).join(' · ')}`
                    : 'Every graded run counts toward the rate.'}
            </div>
        </>
    )
}
