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

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ChoiceQuestionResponseData } from '~/types'

const CATEGORY_LABEL_WIDTH = 280

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
