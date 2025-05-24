import { BindLogic, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { PieChart } from 'scenes/insights/views/LineGraph/PieChart'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { GraphType, InsightLogicProps, SurveyQuestionType } from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

/**
 * SingleChoiceQuestionViz displays a pie chart for single choice questions
 * using a single optimized query to fetch all survey results at once
 */
export function SingleChoiceQuestionViz({ questionIndex }: { questionIndex: number }): JSX.Element | null {
    const { survey, consolidatedSurveyResults, consolidatedSurveyResultsLoading } = useValues(surveyLogic)

    const question = survey.questions[questionIndex]
    if (question.type !== SurveyQuestionType.SingleChoice || !question.id) {
        return null
    }

    // Insights colors

    // Use consolidated data if available, otherwise show loading state
    const processedData = consolidatedSurveyResults ? consolidatedSurveyResults.responsesByQuestion[question.id] : null

    if (consolidatedSurveyResultsLoading) {
        return <div>loading surveys data</div>
    }

    if (!processedData) {
        return <div>No responses yet</div>
    }

    const { data, total } = processedData

    if (!data || data.length === 0) {
        return <div>No responses yet</div>
    }

    return (
        <div className="flex flex-col gap-2">
            <div>
                <div className="font-semibold text-secondary">Single choice</div>
                <div className="text-xl font-bold mb-2">
                    Question {questionIndex + 1}: {question.question}
                </div>
            </div>
            <div className="h-80 overflow-y-auto border rounded pt-4 pb-2 flex">
                <div className="relative h-full w-80">
                    <BindLogic logic={insightLogic} props={insightProps}>
                        <PieChart
                            labelGroupType={1}
                            data-attr="survey-rating"
                            type={GraphType.Pie}
                            hideAnnotations={true}
                            formula="-"
                            tooltip={{
                                showHeader: false,
                                hideColorCol: true,
                            }}
                            datasets={[
                                {
                                    id: 1,
                                    data: data.map((d: { value: number }) => d.value),
                                    labels: data.map((d: { label: string }) => d.label),
                                    backgroundColor: data.map(
                                        (_: any, i: number) => CHART_INSIGHTS_COLORS[i % CHART_INSIGHTS_COLORS.length]
                                    ),
                                },
                            ]}
                            labels={data.map((d: { label: string }) => d.label)}
                        />
                    </BindLogic>
                </div>
                <div
                    className={`grid h-full pl-4 ${
                        data.length < 5 ? 'py-20' : data.length < 7 ? 'py-15' : data.length < 10 ? 'py-10' : 'py-5'
                    } grid-cols-${Math.min(Math.ceil(data.length / 10), 3)}`}
                >
                    {data.map((d: { value: number; label: string }, i: number) => {
                        const percentage = ((d.value / total) * 100).toFixed(1)

                        return (
                            <div key={`single-choice-legend-${questionIndex}-${i}`} className="flex items-center mr-6">
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
        </div>
    )
}
