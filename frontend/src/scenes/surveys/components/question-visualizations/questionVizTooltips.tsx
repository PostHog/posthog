import { TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
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

function TooltipRow({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex justify-between gap-4">
            <span className="opacity-60">{label}</span>
            <span className="font-semibold tabular-nums">{value}</span>
        </div>
    )
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
    const swatchColor = ctx.seriesData[0]?.color

    if (!tooltipContext) {
        return (
            <TooltipSurface>
                <span className="font-semibold">{optionLabel}</span>
            </TooltipSurface>
        )
    }

    let inspectLabel = 'Double click to filter'
    if (activeChoiceLabel && optionLabel === activeChoiceLabel) {
        inspectLabel = 'Click to clear filter'
    } else if (activeChoiceLabel) {
        inspectLabel = 'Click to switch filter'
    }

    return (
        <TooltipSurface>
            <div className="flex items-center gap-2 font-semibold mb-1">
                {swatchColor && <TooltipSwatch color={swatchColor} />}
                <span>{optionLabel}</span>
                <span className="font-normal opacity-60">
                    #{tooltipContext.rank} of {chartData.length}
                </span>
            </div>
            <TooltipRow label="Responses" value={String(value)} />
            <TooltipRow label="Respondents" value={`${tooltipContext.respondentPercentage}%`} />
            <TooltipRow label="Of selected options" value={`${tooltipContext.selectionPercentage}%`} />
            <div className="mt-1 opacity-60">{inspectLabel}</div>
        </TooltipSurface>
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
    const swatchColor = ctx.seriesData[0]?.color

    let inspectLabel = 'Click to filter'
    if (activeRatingLabel && ratingLabel === activeRatingLabel) {
        inspectLabel = 'Click to clear filter'
    } else if (activeRatingLabel) {
        inspectLabel = 'Click to switch filter'
    }

    return (
        <TooltipSurface>
            <div className="flex items-center gap-2 font-semibold mb-1">
                {swatchColor && <TooltipSwatch color={swatchColor} />}
                <span>Rating {ratingLabel}</span>
                {npsBucket && <span className={`font-normal ${npsBucket.textClass}`}>{npsBucket.label}</span>}
            </div>
            <TooltipRow label="Responses" value={String(value)} />
            <TooltipRow label="Respondents" value={`${context?.respondentPercentage ?? '0.0'}%`} />
            <div className="mt-1 opacity-60">{inspectLabel}</div>
        </TooltipSurface>
    )
}
