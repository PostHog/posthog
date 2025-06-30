import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import { ChoiceQuestionResponseData } from 'scenes/surveys/surveyLogic'

import { GraphType, InsightLogicProps } from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

const barColor = CHART_INSIGHTS_COLORS[2]

interface Props {
    responseData: ChoiceQuestionResponseData[]
}

export function MultipleChoiceQuestionViz({ responseData }: Props): JSX.Element | null {
    return (
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
                            barPercentage: 0.9,
                            minBarLength: 2,
                            data: responseData.map((d) => d.value),
                            labels: responseData.map((d) => d.label),
                            breakdownValues: responseData.map((d) => d.label),
                            backgroundColor: barColor,
                            borderColor: barColor,
                            hoverBackgroundColor: barColor,
                        },
                    ]}
                    labels={responseData.map((d) => d.label)}
                />
            </BindLogic>
        </div>
    )
}
