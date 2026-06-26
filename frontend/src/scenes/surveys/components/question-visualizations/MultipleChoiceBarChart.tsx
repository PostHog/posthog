import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { BarChart, ValueLabels } from '@posthog/quill-charts'
import type { BarChartConfig, Series, TooltipContext } from '@posthog/quill-charts'

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

// series/labels/config identities gate the chart's internal memos and canvas redraws, so they
// must stay stable across the unrelated re-renders surveyLogic emits during a results requery —
// rebuilding them every render makes the chart visibly flash while a filter reloads.
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

    // Bars encode the share of respondents who picked each choice against a fixed 0–100% domain;
    // counts surface in the labels and tooltip. Per-bar overrides carry the colors — the series
    // color is just the fallback.
    const series = useMemo<Series[]>(
        () => [
            {
                key: 'multiple-choice',
                label: 'Share of respondents',
                data: chartData.map((d) => (totalResponses > 0 ? (d.value / totalResponses) * 100 : 0)),
                color: barColors[0],
                bars: chartData.map((_, i) => ({ color: barColors[i] })),
            },
        ],
        [chartData, totalResponses, barColors]
    )

    // Synthetic band keys keep bars distinct even if two choices share a label; the choice text is
    // rendered through the category-axis formatter instead.
    const labels = useMemo(() => chartData.map((_, i) => String(i)), [chartData])

    const config = useMemo<BarChartConfig>(
        () => ({
            axisOrientation: 'horizontal',
            barLayout: 'grouped',
            hideXAxis: true,
            showGrid: false,
            showAxisLines: false,
            maxCategoryLabelWidth: CATEGORY_LABEL_WIDTH,
            xTickFormatter: (_label, index) => chartData[index]?.label ?? '',
            margins: { top: 4, right: 20, bottom: 4 },
            bars: {
                cornerRadius: 3,
                minBandSize: 32,
                valueDomain: [0, 100],
            },
            tooltip: { placement: 'cursor' },
        }),
        [chartData]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => (
            <ChoiceTooltip
                ctx={ctx}
                chartData={chartData}
                tooltipContextByIndex={tooltipContextByIndex}
                activeChoiceLabel={activeChoiceLabel}
            />
        ),
        [chartData, tooltipContextByIndex, activeChoiceLabel]
    )

    const valueFormatter = useCallback(
        (_value: number, _seriesIndex: number, dataIndex: number): string =>
            formatCountWithPercentage(chartData[dataIndex]?.value ?? 0, totalResponses),
        [chartData, totalResponses]
    )

    return (
        <div className="pl-4">
            <BarChart
                series={series}
                labels={labels}
                config={config}
                theme={theme}
                tooltip={renderTooltip}
                onPointClick={({ dataIndex }) => onBarClick(dataIndex)}
                dataAttr="survey-multiple-choice"
            >
                <ValueLabels valueFormatter={valueFormatter} offset={VALUE_LABEL_OFFSET} />
            </BarChart>
        </div>
    )
}
