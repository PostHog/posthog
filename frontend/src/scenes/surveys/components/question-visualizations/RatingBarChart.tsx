import { useValues } from 'kea'
import { useMemo } from 'react'

import { BarChart, ValueLabels } from '@posthog/quill-charts'
import type { BarChartConfig, Series, TooltipContext } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { formatCountWithPercentage } from 'scenes/surveys/components/question-visualizations/questionVizTransforms'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ChoiceQuestionResponseData } from '~/types'

interface NpsBucketMeta {
    label: string
    textClass: string
}

interface Props {
    data: ChoiceQuestionResponseData[]
    chartLabels: string[]
    totalResponses: number
    barColors: string[]
    activeRatingLabel: string | null
    tooltipContextByIndex: { respondentPercentage: string }[]
    npsBucketByIndex: (NpsBucketMeta | null)[]
    onBarClick: (index: number) => void
}

function RatingTooltip({
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

export function RatingBarChart({
    data,
    chartLabels,
    totalResponses,
    barColors,
    activeRatingLabel,
    tooltipContextByIndex,
    npsBucketByIndex,
    onBarClick,
}: Props): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

    const series: Series[] = [
        {
            key: 'survey-rating',
            label: 'Number of responses',
            data: chartLabels.map((_, i) => data[i]?.value ?? 0),
            color: barColors[0],
            bars: chartLabels.map((_, i) => ({ color: barColors[i] })),
        },
    ]

    const config: BarChartConfig = {
        hideYAxis: true,
        bars: { bandPadding: 0.2 },
    }

    return (
        <div className="relative h-full w-full flex flex-col">
            <BarChart
                series={series}
                labels={chartLabels}
                config={config}
                theme={theme}
                tooltip={(ctx) => (
                    <RatingTooltip
                        ctx={ctx}
                        chartLabels={chartLabels}
                        tooltipContextByIndex={tooltipContextByIndex}
                        npsBucketByIndex={npsBucketByIndex}
                        activeRatingLabel={activeRatingLabel}
                    />
                )}
                onPointClick={({ dataIndex }) => onBarClick(dataIndex)}
                dataAttr="survey-rating"
            >
                <ValueLabels valueFormatter={(value) => formatCountWithPercentage(value, totalResponses)} />
            </BarChart>
        </div>
    )
}
