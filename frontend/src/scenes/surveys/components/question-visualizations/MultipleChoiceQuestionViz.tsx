import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { MultipleChoiceBarChart } from 'scenes/surveys/components/question-visualizations/MultipleChoiceBarChart'
import { OpenQuestionSummaryV2 } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummaryV2'
import { computeBarColors } from 'scenes/surveys/components/question-visualizations/questionVizTransforms'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import { VirtualizedResponseList } from 'scenes/surveys/components/question-visualizations/VirtualizedResponseList'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

import { themeLogic } from '~/layout/navigation/themeLogic'
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
    const { isDarkModeOn } = useValues(themeLogic)

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
            !!activeChoiceLabel,
            isDarkModeOn
        )
    }, [activeChoiceLabel, chartData, highlightedChoiceLabel, isDarkModeOn])

    const tooltipContextByIndex = useMemo((): TooltipContext[] => {
        const totalSelections = chartData.reduce((sum, d) => sum + d.value, 0)

        // chartData is sorted by value, so the row position is the rank — no tie-skipping,
        // which read as the tooltip showing the "wrong" number.
        return chartData.map((entry, index) => ({
            rank: index + 1,
            respondentPercentage: totalResponses > 0 ? ((entry.value / totalResponses) * 100).toFixed(1) : '0.0',
            selectionPercentage: totalSelections > 0 ? ((entry.value / totalSelections) * 100).toFixed(1) : '0.0',
        }))
    }, [chartData, totalResponses])

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

    const applyChoiceClick = (index: number): void => {
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

        if (activeChoiceLabel && activeChoiceLabel !== clickedChoiceLabel) {
            upsertChoiceAnswerFilter(clickedChoiceLabel)
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
                <MultipleChoiceBarChart
                    chartData={chartData}
                    totalResponses={totalResponses}
                    activeChoiceLabel={activeChoiceLabel}
                    barColors={barColors}
                    tooltipContextByIndex={tooltipContextByIndex}
                    onBarClick={applyChoiceClick}
                />
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
