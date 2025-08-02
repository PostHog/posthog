import { BindLogic } from 'kea'
import { useMemo } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { ResponseCard } from 'scenes/surveys/components/question-visualizations/ResponseCard'
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

interface ProcessedData {
    chartData: ChoiceQuestionResponseData[]
    openEndedResponses: ChoiceQuestionResponseData[]
}

export function MultipleChoiceQuestionViz({ responseData }: Props): JSX.Element | null {
    const { chartData, openEndedResponses } = useMemo((): ProcessedData => {
        const predefinedResponses = responseData.filter((d) => d.isPredefined)
        const nonPredefinedResponses = responseData.filter((d) => !d.isPredefined)

        // Separate popular vs unique non-predefined responses
        const popularNonPredefined = nonPredefinedResponses.filter((d) => d.value >= 2)
        const uniqueNonPredefined = nonPredefinedResponses.filter((d) => d.value === 1)

        // Chart shows: predefined + popular open-ended responses (2+)
        const chartData = [...predefinedResponses, ...popularNonPredefined]

        // Only group truly unique responses (count = 1) into "Other (open-ended)"
        if (uniqueNonPredefined.length > 0) {
            const totalOtherCount = uniqueNonPredefined.reduce((sum, d) => sum + d.value, 0)
            chartData.push({
                label: 'Other (open-ended)',
                value: totalOtherCount,
                isPredefined: false,
            })
        }

        // Sort by value descending
        chartData.sort((a, b) => b.value - a.value)

        return {
            chartData,
            openEndedResponses: uniqueNonPredefined, // Only show unique responses in the grid
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
                                barPercentage: 0.9,
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
                <div className="border rounded p-4">
                    <h4 className="font-semibold mb-3 text-sm text-muted-foreground">Unique open-ended responses:</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                        {openEndedResponses.slice(0, 20).map((response, i) => (
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
                            <div className="border rounded p-3 bg-surface-primary flex items-center justify-center text-sm text-muted-foreground hover:bg-surface-secondary cursor-pointer transition-colors">
                                <div className="text-center">
                                    <div className="font-medium">+{openEndedResponses.length - 20} more responses</div>
                                    <div className="text-xs mt-1">Check all of them in the table below</div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
