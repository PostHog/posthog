import { useValues } from 'kea'
import { useMemo } from 'react'

import { BarChart, ValueLabels } from '@posthog/quill-charts'
import type { BarChartConfig, Series } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import {
    ChoiceTooltip,
    ChoiceTooltipContextData,
} from 'scenes/surveys/components/question-visualizations/questionVizTooltips'
import { formatCountWithPercentage } from 'scenes/surveys/components/question-visualizations/questionVizTransforms'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ChoiceQuestionResponseData } from '~/types'

const CATEGORY_LABEL_WIDTH = 280
// Gap between the bar tip and its value label.
const VALUE_LABEL_OFFSET = 6

// Upper bound for the bar track: a bit past the longest bar, rounded up to a clean step — so the
// hatched remainder reads as headroom rather than an empty axis (mirrors ToolErrorRateChart).
function niceCountAxisMax(maxValue: number): number {
    const padded = Math.max(1, maxValue) * 1.4
    let step = Math.max(1, 10 ** Math.floor(Math.log10(padded)))
    let axisMax = Math.ceil(padded / step) * step
    if (axisMax / padded > 1.5 && step > 1) {
        step /= 2
        axisMax = Math.ceil(padded / step) * step
    }
    return axisMax
}

interface Props {
    chartData: ChoiceQuestionResponseData[]
    totalResponses: number
    activeChoiceLabel: string | null
    barColors: string[]
    tooltipContextByIndex: ChoiceTooltipContextData[]
    onBarClick: (index: number) => void
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

    // Stable series color: the bar track tint derives from it, so it must not follow the
    // per-bar dim applied while a choice filter is active.
    const series: Series[] = [
        {
            key: 'multiple-choice',
            label: 'Number of responses',
            data: chartData.map((d) => d.value),
            color: CHART_INSIGHTS_COLORS[0],
            bars: chartData.map((_, i) => ({ color: barColors[i] })),
        },
    ]

    // Synthetic band keys keep bars distinct even if two choices share a label; the choice text is
    // rendered through the category-axis formatter instead.
    const labels = chartData.map((_, i) => String(i))

    const axisMax = niceCountAxisMax(Math.max(0, ...chartData.map((d) => d.value)))
    const config: BarChartConfig = {
        axisOrientation: 'horizontal',
        barLayout: 'grouped',
        showGrid: false,
        showAxisLines: false,
        maxCategoryLabelWidth: CATEGORY_LABEL_WIDTH,
        xTickFormatter: (_label, index) => chartData[index]?.label ?? '',
        // Counts: d3 picks fractional tick steps on small domains, which round to duplicate labels.
        yTickFormatter: (value) => (Number.isInteger(value) ? String(value) : ''),
        margins: { top: 4, right: 20, bottom: 22 },
        bars: {
            cornerRadius: 3,
            minBandSize: 32,
            track: { hover: false },
            valueDomain: [0, axisMax],
        },
        tooltip: { placement: 'cursor' },
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
                <ValueLabels
                    valueFormatter={(value) => formatCountWithPercentage(value, totalResponses)}
                    offset={VALUE_LABEL_OFFSET}
                />
            </BarChart>
        </div>
    )
}
