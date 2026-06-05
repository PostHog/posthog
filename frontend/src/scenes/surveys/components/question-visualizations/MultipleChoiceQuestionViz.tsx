import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { BarChart, MAX_CATEGORY_LABEL_WIDTH, ValueLabels } from '@posthog/quill-charts'
import type { BarChartConfig, PointClickData, Series, TooltipContext } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { OpenQuestionSummaryV2 } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummaryV2'
import {
    computeBarColors,
    resolveChoiceClick,
} from 'scenes/surveys/components/question-visualizations/questionVizTransforms'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import { VirtualizedResponseList } from 'scenes/surveys/components/question-visualizations/VirtualizedResponseList'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

import {
    ChoiceQuestionResponseData,
    EventPropertyFilter,
    MultipleSurveyQuestion,
    OpenQuestionResponseData,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

interface Props {
    question: MultipleSurveyQuestion
    questionIndex: number
    responseData: ChoiceQuestionResponseData[]
    totalResponses: number
}

interface ProcessedData {
    chartData: ChoiceQuestionResponseData[]
    openEndedResponses: ChoiceQuestionResponseData[]
}

interface TooltipContextData {
    rank: number
    respondentPercentage: string
    selectionPercentage: string
}

function toOpenQuestionFormat(responses: ChoiceQuestionResponseData[]): OpenQuestionResponseData[] {
    return responses.map((r) => ({
        distinctId: r.distinctId || '',
        response: r.label,
        personDisplayName: r.personDisplayName,
        timestamp: r.timestamp,
    }))
}

function OpenEndedResponsesSection({
    openEndedResponses,
    questionId,
    questionIndex,
}: {
    openEndedResponses: ChoiceQuestionResponseData[]
    questionId?: string
    questionIndex: number
}): JSX.Element {
    return (
        <div className="space-y-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Open-ended responses</h4>
            <OpenQuestionSummaryV2
                questionId={questionId}
                questionIndex={questionIndex}
                totalResponses={openEndedResponses.length}
            />
            <VirtualizedResponseList
                responses={toOpenQuestionFormat(openEndedResponses)}
                className="rounded-md border bg-surface-secondary/60 p-2"
            />
        </div>
    )
}

export function MultipleChoiceQuestionViz({
    question,
    questionIndex,
    responseData,
    totalResponses,
}: Props): JSX.Element | null {
    const { answerFilters } = useValues(surveyLogic)
    const { setAnswerFilters } = useActions(surveyLogic)
    const theme = useMemo(() => buildTheme(), [])

    const { chartData, openEndedResponses } = useMemo((): ProcessedData => {
        const predefinedResponses = responseData.filter((d) => d.isPredefined)
        const nonPredefinedResponses = responseData.filter((d) => !d.isPredefined)

        const chartData = [...predefinedResponses]

        if (nonPredefinedResponses.length > 0) {
            const totalOpenEndedCount = nonPredefinedResponses.reduce((sum, d) => sum + d.value, 0)
            chartData.push({
                label: 'Other (open-ended)',
                value: totalOpenEndedCount,
                isPredefined: true,
            })
        }

        chartData.sort((a, b) => b.value - a.value)

        return {
            chartData,
            openEndedResponses: nonPredefinedResponses,
        }
    }, [responseData])

    const responseFilterKey = question.id ? getSurveyIdBasedResponseKey(question.id) : null
    const [armedChoiceLabel, setArmedChoiceLabel] = useState<string | null>(null)

    useEffect(() => {
        if (!armedChoiceLabel) {
            return
        }

        const timeout = setTimeout(() => setArmedChoiceLabel(null), 2500)
        return () => clearTimeout(timeout)
    }, [armedChoiceLabel])

    const currentQuestionFilter = useMemo(
        () =>
            responseFilterKey
                ? (answerFilters.find(
                      (filter) => filter.key === responseFilterKey && filter.type === PropertyFilterType.Event
                  ) as EventPropertyFilter | undefined)
                : undefined,
        [answerFilters, responseFilterKey]
    )

    const activeChoiceLabel = useMemo((): string | null => {
        if (!currentQuestionFilter || currentQuestionFilter.operator !== PropertyOperator.IContains) {
            return null
        }

        if (Array.isArray(currentQuestionFilter.value)) {
            return currentQuestionFilter.value.length === 1 ? String(currentQuestionFilter.value[0]) : null
        }

        return typeof currentQuestionFilter.value === 'string' && currentQuestionFilter.value
            ? currentQuestionFilter.value
            : null
    }, [currentQuestionFilter])

    const highlightedChoiceLabel = activeChoiceLabel || armedChoiceLabel

    const barColors = useMemo(() => {
        const baseColors = chartData.map((_, i) => CHART_INSIGHTS_COLORS[i % CHART_INSIGHTS_COLORS.length])
        return computeBarColors(
            baseColors,
            chartData.map((d) => d.label),
            highlightedChoiceLabel,
            !!activeChoiceLabel
        )
    }, [activeChoiceLabel, chartData, highlightedChoiceLabel])

    const tooltipContextByIndex = useMemo((): TooltipContextData[] => {
        const totalSelections = chartData.reduce((sum, d) => sum + d.value, 0)
        let currentRank = 0
        let previousValue: number | null = null

        return chartData.map((entry, index) => {
            if (entry.value !== previousValue) {
                currentRank = index + 1
                previousValue = entry.value
            }

            return {
                rank: currentRank,
                respondentPercentage: totalResponses > 0 ? ((entry.value / totalResponses) * 100).toFixed(1) : '0.0',
                selectionPercentage: totalSelections > 0 ? ((entry.value / totalSelections) * 100).toFixed(1) : '0.0',
            }
        })
    }, [chartData, totalResponses])

    const series = useMemo<Series[]>(
        () => [
            {
                key: 'multiple-choice',
                label: 'Number of responses',
                data: chartData.map((d) => d.value),
                color: barColors[0],
                bars: chartData.map((_, i) => ({ color: barColors[i] })),
            },
        ],
        [chartData, barColors]
    )

    // Synthetic band keys keep bars distinct even if two choices share a label; the choice text is
    // rendered through the category-axis formatter instead.
    const labels = useMemo(() => chartData.map((_, i) => String(i)), [chartData])

    const config = useMemo<BarChartConfig>(
        () => ({
            hideXAxis: true,
            axisOrientation: 'horizontal',
            maxCategoryLabelWidth: MAX_CATEGORY_LABEL_WIDTH,
            xTickFormatter: (_label, index) => chartData[index]?.label ?? '',
            bars: { minBandSize: 48, bandPadding: 0.2 },
        }),
        [chartData]
    )

    const valueLabelFormatter = (value: number): string => {
        const total = totalResponses || 1
        const percentage = ((value / total) * 100).toFixed(1)
        return `${value} (${percentage}%)`
    }

    const renderTooltip = (ctx: TooltipContext): JSX.Element | null => {
        const optionLabel = chartData[ctx.dataIndex]?.label ?? ctx.seriesData[0]?.series.label ?? ''
        const tooltipContext = tooltipContextByIndex[ctx.dataIndex]
        const value = ctx.seriesData[0]?.value ?? 0

        let inspectLabel = 'Double click to filter'
        if (activeChoiceLabel && optionLabel === activeChoiceLabel) {
            inspectLabel = 'Click to clear filter'
        } else if (activeChoiceLabel) {
            inspectLabel = 'Click to switch filter'
        }

        if (!tooltipContext) {
            return (
                <div className="bg-surface-primary border rounded-md shadow-md px-3 py-2 text-sm">
                    <span className="font-medium">{optionLabel}</span>
                </div>
            )
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
                    <span className="font-semibold text-primary">{tooltipContext.respondentPercentage}%</span>{' '}
                    respondents
                    <span className="mx-1 text-muted-alt">•</span>
                    <span className="font-medium text-primary">{tooltipContext.selectionPercentage}%</span> of all
                    selected options
                </div>
                <div className="text-xs text-muted mt-1">{inspectLabel}</div>
            </div>
        )
    }

    const upsertChoiceAnswerFilter = (choiceLabel: string | null): void => {
        if (!responseFilterKey) {
            return
        }

        const updatedFilters = [...answerFilters]
        const existingIndex = updatedFilters.findIndex((f) => f.key === responseFilterKey)

        if (existingIndex >= 0) {
            if (choiceLabel) {
                updatedFilters[existingIndex] = {
                    ...updatedFilters[existingIndex],
                    key: responseFilterKey,
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.IContains,
                    value: choiceLabel,
                }
            } else {
                updatedFilters.splice(existingIndex, 1)
            }
        } else if (choiceLabel) {
            updatedFilters.push({
                key: responseFilterKey,
                type: PropertyFilterType.Event,
                operator: PropertyOperator.IContains,
                value: choiceLabel,
            })
        }

        setAnswerFilters(updatedFilters)
    }

    const handleChoiceBarClick = ({ dataIndex }: PointClickData): void => {
        if (!responseFilterKey) {
            return
        }

        const clickedChoiceLabel = chartData[dataIndex]?.label
        if (!clickedChoiceLabel) {
            return
        }

        const { upsert, nextArmed } = resolveChoiceClick(activeChoiceLabel, armedChoiceLabel, clickedChoiceLabel)
        if (upsert) {
            upsertChoiceAnswerFilter(upsert.value)
        }
        setArmedChoiceLabel(nextArmed)
    }

    return (
        <div className="space-y-4">
            <div className="border rounded py-4 max-h-[600px] overflow-y-auto">
                <BarChart
                    series={series}
                    labels={labels}
                    config={config}
                    theme={theme}
                    tooltip={renderTooltip}
                    onPointClick={handleChoiceBarClick}
                    dataAttr="survey-multiple-choice"
                >
                    <ValueLabels valueFormatter={valueLabelFormatter} />
                </BarChart>
            </div>
            {responseFilterKey && (
                <div className="text-xs text-muted text-center">
                    {activeChoiceLabel ? (
                        <>
                            Showing only "{activeChoiceLabel}" responses.{' '}
                            <button
                                className="text-link font-medium hover:underline cursor-pointer"
                                onClick={() => upsertChoiceAnswerFilter(null)}
                            >
                                Clear filter
                            </button>{' '}
                            or click another bar to switch.
                        </>
                    ) : armedChoiceLabel ? (
                        `Click "${armedChoiceLabel}" again to filter by this choice.`
                    ) : (
                        'Double-click an option to filter by that choice.'
                    )}
                </div>
            )}

            {openEndedResponses.length > 0 && (
                <OpenEndedResponsesSection
                    openEndedResponses={openEndedResponses}
                    questionId={question.id}
                    questionIndex={questionIndex}
                />
            )}
        </div>
    )
}
