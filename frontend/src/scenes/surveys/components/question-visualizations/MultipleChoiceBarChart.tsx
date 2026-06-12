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
// Gap between the bar tip and its value label.
const VALUE_LABEL_OFFSET = 6

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

    // Bars encode the share of respondents who picked each choice, so the 0–100% axis and the
    // hatched track remainder both mean something; counts surface in the labels and tooltip.
    // The series color only tints the bar track here (every bar has its own override), so use a
    // stable theme neutral: the track stays a subtle texture instead of pulling a palette color,
    // and it doesn't follow the per-bar dim applied while a choice filter is active.
    const series: Series[] = [
        {
            key: 'multiple-choice',
            label: 'Share of respondents',
            data: chartData.map((d) => (totalResponses > 0 ? (d.value / totalResponses) * 100 : 0)),
            color: theme.crosshairColor ?? 'gray',
            bars: chartData.map((_, i) => ({ color: barColors[i] })),
        },
    ]

    // Synthetic band keys keep bars distinct even if two choices share a label; the choice text is
    // rendered through the category-axis formatter instead.
    const labels = chartData.map((_, i) => String(i))

    const config: BarChartConfig = {
        axisOrientation: 'horizontal',
        barLayout: 'grouped',
        showGrid: false,
        showAxisLines: false,
        maxCategoryLabelWidth: CATEGORY_LABEL_WIDTH,
        xTickFormatter: (_label, index) => chartData[index]?.label ?? '',
        yTickFormatter: (value) => (Number.isInteger(value) ? `${value}%` : ''),
        margins: { top: 4, right: 20, bottom: 22 },
        bars: {
            cornerRadius: 3,
            minBandSize: 32,
            track: { hover: false },
            valueDomain: [0, 100],
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
                    valueFormatter={(_value, _seriesIndex, dataIndex) =>
                        formatCountWithPercentage(chartData[dataIndex]?.value ?? 0, totalResponses)
                    }
                    offset={VALUE_LABEL_OFFSET}
                />
            </BarChart>
        </div>
    )
}
