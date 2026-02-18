import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { OpenQuestionSummaryV2 } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummaryV2'
import { VirtualizedResponseList } from 'scenes/surveys/components/question-visualizations/VirtualizedResponseList'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'

import {
    ChoiceQuestionResponseData,
    GraphType,
    InsightLogicProps,
    MultipleSurveyQuestion,
    OpenQuestionResponseData,
} from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

const barColor = CHART_INSIGHTS_COLORS[2]

interface Props {
    question: MultipleSurveyQuestion
    questionIndex: number
    responseData: ChoiceQuestionResponseData[]
    totalResponses: number
}

interface ProcessedData {
    chartData: ChoiceQuestionResponseData[]
    nonPredefinedResponses: ChoiceQuestionResponseData[]
}

function toOpenQuestionFormat(responses: ChoiceQuestionResponseData[]): OpenQuestionResponseData[] {
    return responses.map((r) => ({
        distinctId: r.distinctId || '',
        response: r.label,
        personDisplayName: r.personDisplayName,
        timestamp: r.timestamp,
    }))
}

function NonPredefinedResponsesSection({
    responses,
    questionId,
    questionIndex,
}: {
    responses: ChoiceQuestionResponseData[]
    questionId?: string
    questionIndex: number
}): JSX.Element {
    return (
        <div>
            <h4 className="font-semibold mb-3 text-sm text-muted-foreground">
                <Tooltip title="Includes open-ended responses and responses to choices that have been edited or removed">
                    <span>Other responses</span>
                    <IconInfo className="text-lg text-secondary shrink-0 ml-0.5 mt-0.5" />
                </Tooltip>
            </h4>
            <OpenQuestionSummaryV2
                questionId={questionId}
                questionIndex={questionIndex}
                totalResponses={responses.length}
            />
            <VirtualizedResponseList responses={toOpenQuestionFormat(responses)} />
        </div>
    )
}

export function MultipleChoiceQuestionViz({
    question,
    questionIndex,
    responseData,
    totalResponses,
}: Props): JSX.Element | null {
    const { chartData, nonPredefinedResponses } = useMemo((): ProcessedData => {
        const predefinedResponses = responseData.filter((d) => d.isPredefined)
        const nonPredefinedResponses = responseData.filter((d) => !d.isPredefined)

        const chartData = [...predefinedResponses]

        if (nonPredefinedResponses.length > 0) {
            const totalNonPredefinedCount = nonPredefinedResponses.reduce((sum, d) => sum + d.value, 0)
            chartData.push({
                label: 'Other',
                value: totalNonPredefinedCount,
                isPredefined: true,
            })
        }

        chartData.sort((a, b) => b.value - a.value)

        return {
            chartData,
            nonPredefinedResponses,
        }
    }, [responseData])

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
                        tooltip={{
                            showHeader: false,
                            hideColorCol: true,
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
                                backgroundColor: barColor,
                                borderColor: barColor,
                                hoverBackgroundColor: barColor,
                                totalResponses,
                            },
                        ]}
                        labels={chartData.map((d) => d.label)}
                    />
                </BindLogic>
            </div>

            {nonPredefinedResponses.length > 0 && (
                <NonPredefinedResponsesSection
                    responses={nonPredefinedResponses}
                    questionId={question.id}
                    questionIndex={questionIndex}
                />
            )}
        </div>
    )
}
