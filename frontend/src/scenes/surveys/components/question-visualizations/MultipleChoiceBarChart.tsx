import { useValues } from 'kea'
import { useMemo } from 'react'

import { BarChart, ValueLabels } from '@posthog/quill-charts'
import type { BarChartConfig, Series, TooltipContext } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { formatCountWithPercentage } from 'scenes/surveys/components/question-visualizations/questionVizTransforms'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ChoiceQuestionResponseData } from '~/types'

const CATEGORY_LABEL_WIDTH = 280

interface TooltipContextData {
    rank: number
    respondentPercentage: string
    selectionPercentage: string
}

interface Props {
    chartData: ChoiceQuestionResponseData[]
    totalResponses: number
    activeChoiceLabel: string | null
    barColors: string[]
    tooltipContextByIndex: TooltipContextData[]
    onBarClick: (index: number) => void
}

function ChoiceTooltip({
    ctx,
    chartData,
    tooltipContextByIndex,
    activeChoiceLabel,
}: {
    ctx: TooltipContext
    chartData: ChoiceQuestionResponseData[]
    tooltipContextByIndex: TooltipContextData[]
    activeChoiceLabel: string | null
}): JSX.Element {
    const optionLabel = chartData[ctx.dataIndex]?.label ?? ctx.seriesData[0]?.series.label ?? ''
    const tooltipContext = tooltipContextByIndex[ctx.dataIndex]
    const value = ctx.seriesData[0]?.value ?? 0

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

export function MultipleChoiceBarChart({
    chartData,
    totalResponses,
    activeChoiceLabel,
    barColors,
    tooltipContextByIndex,
    onBarClick,
}: Props): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

    const series: Series[] = [
        {
            key: 'multiple-choice',
            label: 'Number of responses',
            data: chartData.map((d) => d.value),
            color: barColors[0],
            bars: chartData.map((_, i) => ({ color: barColors[i] })),
        },
    ]

    // Synthetic band keys keep bars distinct even if two choices share a label; the choice text is
    // rendered through the category-axis formatter instead.
    const labels = chartData.map((_, i) => String(i))

    const config: BarChartConfig = {
        hideXAxis: true,
        axisOrientation: 'horizontal',
        maxCategoryLabelWidth: CATEGORY_LABEL_WIDTH,
        xTickFormatter: (_label, index) => chartData[index]?.label ?? '',
        bars: { minBandSize: 32, bandPadding: 0.4 },
    }

    return (
        <div className="pl-4">
            <BarChart
                series={series}
                labels={labels}
                config={config}
                theme={theme}
                tooltip={(ctx) => (
                    <ChoiceTooltip
                        ctx={ctx}
                        chartData={chartData}
                        tooltipContextByIndex={tooltipContextByIndex}
                        activeChoiceLabel={activeChoiceLabel}
                    />
                )}
                onPointClick={({ dataIndex }) => onBarClick(dataIndex)}
                dataAttr="survey-multiple-choice"
            >
                <ValueLabels valueFormatter={(value) => formatCountWithPercentage(value, totalResponses)} />
            </BarChart>
        </div>
    )
}
