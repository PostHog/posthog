import type { TooltipContext } from '@posthog/quill-charts'

import { ChoiceQuestionResponseData } from '~/types'

export interface ChoiceTooltipContextData {
    rank: number
    respondentPercentage: string
    selectionPercentage: string
}

export interface NpsBucketMeta {
    label: string
    textClass: string
}

export function ChoiceTooltip({
    ctx,
    chartData,
    tooltipContextByIndex,
    activeChoiceLabel,
}: {
    ctx: TooltipContext
    chartData: ChoiceQuestionResponseData[]
    tooltipContextByIndex: ChoiceTooltipContextData[]
    activeChoiceLabel: string | null
}): JSX.Element {
    const optionLabel = chartData[ctx.dataIndex]?.label ?? ctx.seriesData[0]?.series.label ?? ''
    const tooltipContext = tooltipContextByIndex[ctx.dataIndex]
    // The series carries percentages (the bar axis is share of respondents) — counts live in chartData.
    const value = chartData[ctx.dataIndex]?.value ?? 0

    if (!tooltipContext) {
        return (
            <div className="bg-surface-primary border rounded-md shadow-md px-3 py-2 text-sm">
                <span className="font-medium">{optionLabel}</span>
            </div>
        )
    }

    let inspectLabel = 'Double click to filter'
    if (activeChoiceLabel && optionLabel === activeChoiceLabel) {
        inspectLabel = 'Click to clear filter'
    } else if (activeChoiceLabel) {
        inspectLabel = 'Click to switch filter'
    }

    return (
        <div className="bg-surface-primary border rounded-md shadow-md px-3 py-2 text-sm">
            <div className="flex items-center gap-2 leading-tight">
                <span className="font-semibold">{optionLabel}</span>
                <span className="text-xs text-muted-alt">
                    #{tooltipContext.rank} of {chartData.length}
                </span>
            </div>
            <div className="text-xs text-secondary leading-tight mt-0.5">
                <span className="font-semibold tabular-nums text-primary">{value}</span> responses
                <span className="mx-1 text-muted-alt">•</span>
                <span className="font-semibold text-primary">{tooltipContext.respondentPercentage}%</span> respondents
                <span className="mx-1 text-muted-alt">•</span>
                <span className="font-medium text-primary">{tooltipContext.selectionPercentage}%</span> of all selected
                options
            </div>
            <div className="text-xs text-muted mt-1">{inspectLabel}</div>
        </div>
    )
}

export function RatingTooltip({
    ctx,
    chartLabels,
    tooltipContextByIndex,
    npsBucketByIndex,
    activeRatingLabel,
}: {
    ctx: TooltipContext
    chartLabels: string[]
    tooltipContextByIndex: { respondentPercentage: string }[]
    npsBucketByIndex: (NpsBucketMeta | null)[]
    activeRatingLabel: string | null
}): JSX.Element {
    const ratingLabel = chartLabels[ctx.dataIndex] ?? String(ctx.dataIndex + 1)
    const context = tooltipContextByIndex[ctx.dataIndex]
    const value = ctx.seriesData[0]?.value ?? 0
    const npsBucket = npsBucketByIndex[ctx.dataIndex]

    let inspectLabel = 'Click to filter'
    if (activeRatingLabel && ratingLabel === activeRatingLabel) {
        inspectLabel = 'Click to clear filter'
    } else if (activeRatingLabel) {
        inspectLabel = 'Click to switch filter'
    }

    return (
        <div className="bg-surface-primary border rounded-md shadow-md px-3 py-2 text-sm">
            <div className="flex items-center gap-2 leading-tight">
                <span className="font-semibold">Rating {ratingLabel}</span>
                {npsBucket && <span className={`text-xs ${npsBucket.textClass}`}>{npsBucket.label}</span>}
            </div>
            <div className="text-xs text-secondary leading-tight mt-0.5">
                <span className="font-semibold tabular-nums text-primary">{value}</span> responses
                <span className="mx-1 text-muted-alt">•</span>
                <span className="font-semibold text-primary">{context?.respondentPercentage ?? '0.0'}%</span>{' '}
                respondents
            </div>
            <div className="text-xs text-muted mt-1">{inspectLabel}</div>
        </div>
    )
}
