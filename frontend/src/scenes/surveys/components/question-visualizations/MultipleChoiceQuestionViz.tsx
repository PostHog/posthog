import { BindLogic, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import { QuestionProcessedData, surveyLogic } from 'scenes/surveys/surveyLogic'

import { GraphType, InsightLogicProps, SurveyQuestionType } from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

const barColor = CHART_INSIGHTS_COLORS[2]

/**
 * SingleChoiceQuestionViz displays a pie chart for single choice questions
 * using a single optimized query to fetch all survey results at once
 */
export function MultipleChoiceQuestionViz({ questionIndex }: { questionIndex: number }): JSX.Element | null {
    const { survey, consolidatedSurveyResults, consolidatedSurveyResultsLoading } = useValues(surveyLogic)

    const question = survey.questions[questionIndex]
    if (question.type !== SurveyQuestionType.MultipleChoice || !question.id) {
        return null
    }

    // Use consolidated data if available, otherwise show loading state
    const processedData: QuestionProcessedData | null = consolidatedSurveyResults
        ? consolidatedSurveyResults.responsesByQuestion[question.id]
        : null

    if (consolidatedSurveyResultsLoading) {
        return <div>loading surveys data</div>
    }

    if (!processedData) {
        return <div>No responses yet</div>
    }

    const { data } = processedData

    if (!data || data.length === 0) {
        return <div>No responses yet</div>
    }

    return (
        <div className="flex flex-col gap-2">
            <div>
                <div className="font-semibold text-secondary">Multiple choice</div>
                <div className="text-xl font-bold mb-2">
                    Question {questionIndex + 1}: {question.question}
                </div>
                <div
                    className="border rounded pt-8 pr-10 overflow-y-scroll"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: 600 }}
                >
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
                                    barPercentage: 0.9,
                                    minBarLength: 2,
                                    data: data.map((d) => d.value),
                                    labels: data.map((d) => d.label),
                                    breakdownValues: data.map((d) => d.label),
                                    backgroundColor: barColor,
                                    borderColor: barColor,
                                    hoverBackgroundColor: barColor,
                                },
                            ]}
                            labels={data.map((d) => d.label)}
                        />
                    </BindLogic>
                </div>
            </div>
        </div>
    )
}
