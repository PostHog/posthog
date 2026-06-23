import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { BarChart, ValueLabels } from '@posthog/quill-charts'
import type { BarChartConfig, Series, TooltipContext } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { NpsBucketMeta, RatingTooltip } from 'scenes/surveys/components/question-visualizations/questionVizTooltips'
import { formatCountWithPercentage } from 'scenes/surveys/components/question-visualizations/questionVizTransforms'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ChoiceQuestionResponseData } from '~/types'

// Room above each bar tip for the value label's height, so it floats rather than overlapping the bar.
const VALUE_LABEL_PADDING = 28

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

    const series = useMemo<Series[]>(
        () => [
            {
                key: 'survey-rating',
                label: 'Number of responses',
                data: chartLabels.map((_, i) => data[i]?.value ?? 0),
                color: barColors[0],
                bars: chartLabels.map((_, i) => ({ color: barColors[i] })),
            },
        ],
        [chartLabels, data, barColors]
    )

    const config = useMemo<BarChartConfig>(
        () => ({
            hideYAxis: true,
            bars: { bandPadding: 0.2, valuePadding: VALUE_LABEL_PADDING },
        }),
        []
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => (
            <RatingTooltip
                ctx={ctx}
                chartLabels={chartLabels}
                tooltipContextByIndex={tooltipContextByIndex}
                npsBucketByIndex={npsBucketByIndex}
                activeRatingLabel={activeRatingLabel}
            />
        ),
        [chartLabels, tooltipContextByIndex, npsBucketByIndex, activeRatingLabel]
    )

    const valueFormatter = useCallback(
        (value: number): string => formatCountWithPercentage(value, totalResponses),
        [totalResponses]
    )

    return (
        <div className="relative h-full w-full flex flex-col">
            <BarChart
                series={series}
                labels={chartLabels}
                config={config}
                theme={theme}
                tooltip={renderTooltip}
                onPointClick={({ dataIndex }) => onBarClick(dataIndex)}
                dataAttr="survey-rating"
            >
                <ValueLabels valueFormatter={valueFormatter} />
            </BarChart>
        </div>
    )
}
