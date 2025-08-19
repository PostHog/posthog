import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { ResponseCard, ScrollToSurveyResultsCard } from 'scenes/surveys/components/question-visualizations/ResponseCard'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'

import { ChoiceQuestionResponseData, GraphType, InsightLogicProps } from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

const barColor = CHART_INSIGHTS_COLORS[2]

interface Props {
    responseData: ChoiceQuestionResponseData[]
}

interface ProcessedData {
    chartData: ChoiceQuestionResponseData[]
    openEndedResponses: ChoiceQuestionResponseData[]
}

export function MultipleChoiceQuestionViz({ responseData }: Props): JSX.Element | null {
    const { chartData, openEndedResponses } = useMemo((): ProcessedData => {
        const predefinedResponses = responseData.filter((d) => d.isPredefined)
        const nonPredefinedResponses = responseData.filter((d) => !d.isPredefined)

        // Chart shows predefined responses + total count for "Other" if it exists
        const chartData = [...predefinedResponses]

        // If there are open-ended responses, add a summary count for the predefined "Other" option
        if (nonPredefinedResponses.length > 0) {
            const totalOpenEndedCount = nonPredefinedResponses.reduce((sum, d) => sum + d.value, 0)
            chartData.push({
                label: 'Other (open-ended)',
                value: totalOpenEndedCount,
                isPredefined: true, // This represents the predefined "Other" option
            })
        }

        // Sort by value descending
        chartData.sort((a, b) => b.value - a.value)

        return {
            chartData,
            openEndedResponses: nonPredefinedResponses, // Show all open-ended responses
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
                            },
                        ]}
                        labels={chartData.map((d) => d.label)}
                    />
                </BindLogic>
            </div>

            {openEndedResponses.length > 0 && (
                <div>
                    <h4 className="font-semibold mb-3 text-sm text-muted-foreground">Open-ended responses:</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                        {openEndedResponses.slice(0, openEndedResponses.length > 20 ? 19 : 20).map((response, i) => (
                            <ResponseCard
                                key={`open-${i}`}
                                response={response.label}
                                distinctId={response.distinctId}
                                personProperties={response.personProperties}
                                timestamp={response.timestamp}
                                count={response.value}
                            />
                        ))}
                        {openEndedResponses.length > 20 && (
                            <ScrollToSurveyResultsCard numOfResponses={openEndedResponses.length - 20} />
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
