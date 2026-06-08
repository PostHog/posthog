import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'

import { ChoiceQuestionResponseData, GraphType, InsightLogicProps, SliderSurveyQuestion } from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

interface Props {
    question: SliderSurveyQuestion
    questionIndex: number
    responseData: ChoiceQuestionResponseData[]
    totalResponses: number
}

interface SliderStats {
    average: number
    median: number
    min: number
    max: number
}

function formatValue(value: number, prefix?: string, suffix?: string, decimals = 2): string {
    const rounded = Number.isInteger(value) ? value.toString() : value.toFixed(decimals)
    return `${prefix ?? ''}${rounded}${suffix ?? ''}`
}

function computeStats(responseData: ChoiceQuestionResponseData[]): SliderStats | null {
    if (responseData.length === 0) {
        return null
    }

    const expanded: number[] = []
    for (const entry of responseData) {
        const numericLabel = parseFloat(entry.label)
        if (Number.isNaN(numericLabel)) {
            continue
        }
        for (let i = 0; i < entry.value; i++) {
            expanded.push(numericLabel)
        }
    }

    if (expanded.length === 0) {
        return null
    }

    expanded.sort((a, b) => a - b)

    const sum = expanded.reduce((acc, n) => acc + n, 0)
    const average = sum / expanded.length
    const mid = Math.floor(expanded.length / 2)
    const median = expanded.length % 2 === 0 ? (expanded[mid - 1] + expanded[mid]) / 2 : expanded[mid]

    return {
        average,
        median,
        min: expanded[0],
        max: expanded[expanded.length - 1],
    }
}

function SliderStatCard({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center border rounded p-3 bg-surface-primary min-w-[100px]">
            <span className="text-xs uppercase tracking-wide text-muted">{label}</span>
            <span className="text-lg font-semibold tabular-nums">{value}</span>
        </div>
    )
}

export function SliderQuestionViz({ question, responseData, totalResponses }: Props): JSX.Element | null {
    const stats = useMemo(() => computeStats(responseData), [responseData])

    const chartData = useMemo(
        () =>
            [...responseData].sort((a, b) => {
                const aValue = parseFloat(a.label)
                const bValue = parseFloat(b.label)
                if (Number.isNaN(aValue) || Number.isNaN(bValue)) {
                    return 0
                }
                return aValue - bValue
            }),
        [responseData]
    )

    const labels = useMemo(
        () =>
            chartData.map((d) => {
                const numericLabel = parseFloat(d.label)
                if (Number.isNaN(numericLabel)) {
                    return d.label
                }
                return formatValue(numericLabel, question.prefix, question.suffix, 0)
            }),
        [chartData, question.prefix, question.suffix]
    )

    const barColor = CHART_INSIGHTS_COLORS[0]
    const barColors = chartData.map(() => barColor)

    return (
        <div className="space-y-4">
            {stats && (
                <div className="flex flex-row flex-wrap gap-2">
                    <SliderStatCard
                        label="Average"
                        value={formatValue(stats.average, question.prefix, question.suffix)}
                    />
                    <SliderStatCard
                        label="Median"
                        value={formatValue(stats.median, question.prefix, question.suffix)}
                    />
                    <SliderStatCard label="Min" value={formatValue(stats.min, question.prefix, question.suffix)} />
                    <SliderStatCard label="Max" value={formatValue(stats.max, question.prefix, question.suffix)} />
                </div>
            )}
            <div className="border rounded p-4">
                <BindLogic logic={insightLogic} props={insightProps}>
                    <LineGraph
                        inSurveyView={true}
                        hideYAxis={false}
                        hideXAxis={false}
                        showValuesOnSeries={false}
                        labelGroupType={1}
                        data-attr="survey-slider-histogram"
                        type={GraphType.Bar}
                        formula="-"
                        tooltip={{
                            showHeader: false,
                            hideColorCol: true,
                            groupTypeLabel: 'responses',
                        }}
                        datasets={[
                            {
                                id: 1,
                                label: 'Number of responses',
                                barPercentage: 0.9,
                                minBarLength: 2,
                                data: chartData.map((d) => d.value),
                                labels,
                                backgroundColor: barColors,
                                borderColor: barColors,
                                hoverBackgroundColor: barColors,
                            },
                        ]}
                        labels={labels}
                        datalabelFormatter={(value) => {
                            const total = totalResponses || 1
                            const percentage = ((value / total) * 100).toFixed(1)
                            return `${value} (${percentage}%)`
                        }}
                    />
                </BindLogic>
            </div>
            {(question.lowerBoundLabel || question.upperBoundLabel) && (
                <div className="flex flex-row justify-between text-sm text-secondary px-2">
                    <span>{question.lowerBoundLabel}</span>
                    <span>{question.upperBoundLabel}</span>
                </div>
            )}
        </div>
    )
}
