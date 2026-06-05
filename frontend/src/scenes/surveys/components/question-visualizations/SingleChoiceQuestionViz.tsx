import clsx from 'clsx'
import { useMemo } from 'react'

import { PieChart } from '@posthog/quill-charts'
import type { PieChartConfig, Series, TooltipContext } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'

import { ChoiceQuestionProcessedResponses, MultipleSurveyQuestion } from '~/types'

interface Props {
    question: MultipleSurveyQuestion
    processedData: ChoiceQuestionProcessedResponses
}

const PIE_CONFIG: PieChartConfig = {
    showValueOnSlice: true,
}

function SingleChoiceTooltip({ ctx }: { ctx: TooltipContext }): JSX.Element | null {
    const entry = ctx.seriesData[0]
    if (!entry) {
        return null
    }
    const percentage = ((entry.fraction ?? 0) * 100).toFixed(1)

    return (
        <div className="bg-surface-primary border rounded-md shadow-md px-3 py-2 text-sm">
            <div className="font-semibold leading-tight">{entry.series.label}</div>
            <div className="text-xs text-secondary leading-tight mt-0.5">
                <span className="font-semibold tabular-nums text-primary">{entry.value}</span> responses
                <span className="mx-1 text-muted-alt">•</span>
                <span className="font-semibold text-primary">{percentage}%</span> of total
            </div>
        </div>
    )
}

export function SingleChoiceQuestionViz({
    question,
    processedData: { data, totalResponses },
}: Props): JSX.Element | null {
    const theme = useMemo(() => buildTheme(), [])

    const series = useMemo<Series[]>(
        () =>
            data.map((d, i) => ({
                key: `${i}`,
                label: d.label,
                data: [d.value],
                color: CHART_INSIGHTS_COLORS[i % CHART_INSIGHTS_COLORS.length],
            })),
        [data]
    )

    return (
        <div className="h-80 overflow-y-auto border rounded pt-4 pb-2 flex">
            <div className="relative h-full w-80">
                <PieChart
                    series={series}
                    theme={theme}
                    config={PIE_CONFIG}
                    tooltip={(ctx) => <SingleChoiceTooltip ctx={ctx} />}
                    dataAttr="survey-rating"
                />
            </div>
            <div
                className={clsx(
                    'grid h-full pl-4',
                    data.length < 5 ? 'py-20' : data.length < 7 ? 'py-15' : data.length < 10 ? 'py-10' : 'py-5',
                    Math.min(Math.ceil(data.length / 10), 3) === 1
                        ? 'grid-cols-1'
                        : Math.min(Math.ceil(data.length / 10), 3) === 2
                          ? 'grid-cols-2'
                          : 'grid-cols-3'
                )}
            >
                {data.map((d: { value: number; label: string }, i: number) => {
                    const percentage = ((d.value / totalResponses) * 100).toFixed(1)

                    return (
                        <div key={`single-choice-legend-${question.id}-${i}`} className="flex items-center mr-6">
                            <div
                                className="w-3 h-3 rounded-full mr-2"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: CHART_INSIGHTS_COLORS[i % CHART_INSIGHTS_COLORS.length] }}
                            />
                            <span className="font-semibold text-secondary max-w-48 truncate">{`${d.label}`}</span>
                            <span className="font-bold ml-1 truncate">{` ${percentage}% `}</span>
                            <span className="font-semibold text-secondary ml-1 truncate">{`(${d.value})`}</span>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
