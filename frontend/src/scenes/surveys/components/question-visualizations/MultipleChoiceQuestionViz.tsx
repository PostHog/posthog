import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { hexToRGBA } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { OpenQuestionSummaryV2 } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummaryV2'
import { VirtualizedResponseList } from 'scenes/surveys/components/question-visualizations/VirtualizedResponseList'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

import {
    ChoiceQuestionResponseData,
    EventPropertyFilter,
    GraphPointPayload,
    GraphType,
    InsightLogicProps,
    MultipleSurveyQuestion,
    OpenQuestionResponseData,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

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

interface TooltipContext {
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

    const barColors = useMemo(
        () =>
            chartData.map((entry, i) => {
                const baseColor = CHART_INSIGHTS_COLORS[i % CHART_INSIGHTS_COLORS.length]

                if (!highlightedChoiceLabel || entry.label === highlightedChoiceLabel) {
                    return baseColor
                }

                return hexToRGBA(baseColor, activeChoiceLabel ? 0.22 : 0.35)
            }),
        [activeChoiceLabel, chartData, highlightedChoiceLabel]
    )

    const tooltipContextByIndex = useMemo((): TooltipContext[] => {
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

    const tooltipCountLabel = (value: number): JSX.Element => {
        return <span className="font-semibold tabular-nums">{value}</span>
    }

    const upsertChoiceAnswerFilter = (choiceLabel: string | null): void => {
        if (!responseFilterKey) {
            return
        }

        const updatedFilters = [...answerFilters]
        const existingIndex = updatedFilters.findIndex((f) => f.key === responseFilterKey)

        if (existingIndex >= 0) {
            updatedFilters[existingIndex] = {
                ...updatedFilters[existingIndex],
                key: responseFilterKey,
                type: PropertyFilterType.Event,
                operator: PropertyOperator.IContains,
                value: choiceLabel ?? [],
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

    const handleChoiceBarClick = ({ index }: GraphPointPayload): void => {
        if (!responseFilterKey) {
            return
        }

        const clickedChoiceLabel = chartData[index]?.label
        if (!clickedChoiceLabel) {
            return
        }

        if (activeChoiceLabel === clickedChoiceLabel) {
            upsertChoiceAnswerFilter(null)
            setArmedChoiceLabel(null)
            return
        }

        if (armedChoiceLabel === clickedChoiceLabel) {
            upsertChoiceAnswerFilter(clickedChoiceLabel)
            setArmedChoiceLabel(null)
            return
        }

        setArmedChoiceLabel(clickedChoiceLabel)
    }

    return (
        <div className="space-y-4">
            <div className="border rounded py-4 max-h-[600px] overflow-y-auto">
                <BindLogic logic={insightLogic} props={insightProps}>
                    <LineGraph
                        inSurveyView={true}
                        hideYAxis={true}
                        hideXAxis={true}
                        showValuesOnSeries={true}
                        labelGroupType={1}
                        data-attr="survey-multiple-choice"
                        type={GraphType.HorizontalBar}
                        formula="-"
                        onClick={handleChoiceBarClick}
                        tooltip={{
                            showHeader: false,
                            hideColorCol: true,
                            groupTypeLabel: 'responses (double-click to filter)',
                            renderSeries: (_value, datum) => {
                                const tooltipContext = tooltipContextByIndex[datum.dataIndex]
                                const optionLabel = String(
                                    datum.breakdown_value ?? chartData[datum.dataIndex]?.label ?? datum.label ?? ''
                                )

                                if (!tooltipContext) {
                                    return <span className="font-medium">{optionLabel}</span>
                                }

                                return (
                                    <div className="space-y-0.5">
                                        <div className="flex items-center gap-2 leading-tight">
                                            <span className="font-semibold">{optionLabel}</span>
                                            <span className="text-xs text-muted-alt">
                                                #{tooltipContext.rank} of {chartData.length}
                                            </span>
                                        </div>
                                        <div className="text-xs text-secondary leading-tight">
                                            <span className="font-semibold text-primary">
                                                {tooltipContext.respondentPercentage}%
                                            </span>{' '}
                                            respondents
                                            <span className="mx-1 text-muted-alt">•</span>
                                            <span className="font-medium text-primary">
                                                {tooltipContext.selectionPercentage}%
                                            </span>{' '}
                                            of all selected options
                                        </div>
                                    </div>
                                )
                            },
                            renderCount: tooltipCountLabel,
                        }}
                        datasets={[
                            {
                                id: 1,
                                label: 'Number of responses',
                                barPercentage: 0.8,
                                minBarLength: 2,
                                data: chartData.map((d) => d.value),
                                labels: chartData.map((d) => d.label),
                                breakdownValues: chartData.map((d) => d.label),
                                backgroundColor: barColors,
                                borderColor: barColors,
                                hoverBackgroundColor: barColors,
                                totalResponses,
                            },
                        ]}
                        labels={chartData.map((d) => d.label)}
                    />
                </BindLogic>
            </div>
            {responseFilterKey && (
                <div className="text-xs text-muted text-center">
                    {activeChoiceLabel
                        ? `Showing only responses that selected "${activeChoiceLabel}". Click the same bar to clear.`
                        : armedChoiceLabel
                          ? `Click "${armedChoiceLabel}" again to show only responses that selected it.`
                          : 'Double-click an option to show only responses that selected it.'}
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
