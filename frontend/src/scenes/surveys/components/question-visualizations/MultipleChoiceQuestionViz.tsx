import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import { ChoiceQuestionProcessedData } from 'scenes/surveys/surveyLogic'

import { GraphType, InsightLogicProps } from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

const barColor = CHART_INSIGHTS_COLORS[2]

interface Props {
    processedData: ChoiceQuestionProcessedData
}

/**
 * SingleChoiceQuestionViz displays a pie chart for single choice questions
 * using a single optimized query to fetch all survey results at once
 */
export function MultipleChoiceQuestionViz({ processedData: { data } }: Props): JSX.Element | null {
    if (!data) {
        return <div>No responses yet</div>
    }

    return (
        <div className="border rounded py-4 max-h-[600px] overflow-y-scroll">
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
    )
}
