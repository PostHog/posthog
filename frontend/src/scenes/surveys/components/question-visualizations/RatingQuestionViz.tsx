import { IconInfo } from '@posthog/icons'
import { LemonCollapse, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IntervalFilterStandalone } from 'lib/components/IntervalFilter'
import { dayjs } from 'lib/dayjs'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import { StackedBar, StackedBarSegment, StackedBarSkeleton } from 'scenes/surveys/components/StackedBar'
import {
    NPS_DETRACTOR_LABEL,
    NPS_DETRACTOR_VALUES,
    NPS_PASSIVE_LABEL,
    NPS_PASSIVE_VALUES,
    NPS_PROMOTER_LABEL,
    NPS_PROMOTER_VALUES,
} from 'scenes/surveys/constants'
import { ChoiceQuestionProcessedResponses, surveyLogic } from 'scenes/surveys/surveyLogic'
import { calculateNpsBreakdownFromProcessedData, NPSBreakdown } from 'scenes/surveys/utils'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    ChartDisplayType,
    GraphType,
    InsightLogicProps,
    PropertyFilterType,
    PropertyOperator,
    RatingSurveyQuestion,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
} from '~/types'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

function createNPSTrendSeries(
    values: string[],
    label: string,
    questionIndex: number,
    questionId?: string
): {
    event: string
    kind: NodeKind.EventsNode
    custom_name: string
    properties: Array<{
        type: PropertyFilterType.HogQL
        key: string
    }>
} {
    return {
        event: SurveyEventName.SENT,
        kind: NodeKind.EventsNode,
        custom_name: label,
        properties: [
            {
                type: PropertyFilterType.HogQL,
                key: `getSurveyResponse(${questionIndex}, ${questionId ? `'${questionId}'` : ''}) in (${values.join(
                    ','
                )})`,
            },
        ],
    }
}

function createSingleRatingTrendSeries(
    ratingValue: string,
    questionIndex: number,
    questionId: string
): {
    event: string
    kind: NodeKind.EventsNode
    custom_name: string
    properties: Array<{
        type: PropertyFilterType.HogQL
        key: string
    }>
} {
    return {
        event: SurveyEventName.SENT,
        kind: NodeKind.EventsNode,
        custom_name: `Rating ${ratingValue}`,
        properties: [
            {
                type: PropertyFilterType.HogQL,
                key: `getSurveyResponse(${questionIndex}, '${questionId}') = '${ratingValue}'`,
            },
        ],
    }
}

const CHART_LABELS: Record<number, string[]> = {
    10: ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
    7: ['1', '2', '3', '4', '5', '6', '7'],
    5: ['1', '2', '3', '4', '5'],
    3: ['1', '2', '3'],
}

function NPSStackedBar({ npsBreakdown }: { npsBreakdown: NPSBreakdown }): JSX.Element {
    const segments: StackedBarSegment[] = [
        { count: npsBreakdown.promoters, label: NPS_PROMOTER_LABEL, colorClass: 'bg-success' },
        { count: npsBreakdown.passives, label: NPS_PASSIVE_LABEL, colorClass: 'bg-warning' },
        { count: npsBreakdown.detractors, label: NPS_DETRACTOR_LABEL, colorClass: 'bg-danger' },
    ]

    return <StackedBar segments={segments} />
}

export function NPSBreakdownSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="font-semibold text-secondary">
                <LemonSkeleton className="h-10 w-20" />
                <Tooltip
                    placement="bottom"
                    title="NPS Score is calculated by subtracting the percentage of detractors (0-6) from the percentage of promoters (9-10). Passives (7-8) are not included in the calculation. It can go from -100 to 100."
                >
                    <IconInfo className="text-muted mr-1" />
                    Latest NPS Score
                </Tooltip>
            </div>
            <StackedBarSkeleton />
        </div>
    )
}

function NPSBreakdownViz({ npsBreakdown }: { npsBreakdown: NPSBreakdown }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="font-semibold text-secondary">
                <div className="text-4xl font-bold text-primary">{npsBreakdown.score}</div>
                <Tooltip
                    placement="bottom"
                    title="NPS Score is calculated by subtracting the percentage of detractors (0-6) from the percentage of promoters (9-10). Passives (7-8) are not included in the calculation. It can go from -100 to 100."
                >
                    <IconInfo className="text-muted mr-1" />
                    Latest NPS Score
                </Tooltip>
            </div>
            {npsBreakdown && <NPSStackedBar npsBreakdown={npsBreakdown} />}
        </div>
    )
}

function NPSRatingOverTime({ questionIndex, questionId }: { questionIndex: number; questionId: string }): JSX.Element {
    const { dateRange, interval, compareFilter, defaultInterval, survey } = useValues(surveyLogic)
    const { setDateRange, setInterval, setCompareFilter } = useActions(surveyLogic)

    return (
        <div className="bg-surface-primary rounded">
            <LemonCollapse
                panels={[
                    {
                        key: 'nps-rating-over-time',
                        header: 'NPS Trend Over Time',
                        content: (
                            <div className="flex flex-col gap-2">
                                <div className="flex gap-2 justify-between items-center">
                                    <div className="flex gap-2 items-center">
                                        <DateFilter
                                            dateFrom={dateRange?.date_from ?? undefined}
                                            dateTo={dateRange?.date_to ?? undefined}
                                            onChange={(fromDate, toDate) =>
                                                setDateRange({
                                                    date_from: fromDate,
                                                    date_to: toDate,
                                                })
                                            }
                                        />
                                        <span>grouped by</span>
                                        <IntervalFilterStandalone
                                            interval={interval ?? defaultInterval}
                                            onIntervalChange={setInterval}
                                        />
                                        <CompareFilter
                                            compareFilter={compareFilter}
                                            updateCompareFilter={(compareFilter) => setCompareFilter(compareFilter)}
                                        />
                                    </div>
                                </div>
                                <Query
                                    query={{
                                        kind: NodeKind.InsightVizNode,
                                        source: {
                                            kind: NodeKind.TrendsQuery,
                                            interval: interval ?? defaultInterval,
                                            compareFilter: compareFilter,
                                            dateRange: dateRange ?? {
                                                date_from: dayjs((survey as Survey).created_at).format('YYYY-MM-DD'),
                                                date_to: survey.end_date
                                                    ? dayjs(survey.end_date).format('YYYY-MM-DD')
                                                    : dayjs().add(1, 'day').format('YYYY-MM-DD'),
                                            },
                                            series: [
                                                createNPSTrendSeries(
                                                    NPS_PROMOTER_VALUES,
                                                    NPS_PROMOTER_LABEL,
                                                    questionIndex,
                                                    questionId
                                                ),
                                                createNPSTrendSeries(
                                                    NPS_PASSIVE_VALUES,
                                                    NPS_PASSIVE_LABEL,
                                                    questionIndex,
                                                    questionId
                                                ),
                                                createNPSTrendSeries(
                                                    NPS_DETRACTOR_VALUES,
                                                    NPS_DETRACTOR_LABEL,
                                                    questionIndex,
                                                    questionId
                                                ),
                                            ],
                                            properties: [
                                                {
                                                    type: PropertyFilterType.Event,
                                                    key: SurveyEventProperties.SURVEY_ID,
                                                    operator: PropertyOperator.Exact,
                                                    value: survey.id,
                                                },
                                            ],
                                            trendsFilter: {
                                                formula: '(A / (A+B+C) * 100) - (C / (A+B+C) * 100)',
                                                display: ChartDisplayType.ActionsBar,
                                            },
                                        },
                                    }}
                                    readOnly
                                />
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}

/**
 * Component that displays average rating trends over time for rating scales 3, 5, and 7.
 *
 * This component creates a trend chart that shows how the average rating changes over time.
 * It works by:
 * 1. Creating separate event series for each possible rating value (1, 2, 3 for scale 3, etc.)
 * 2. Using a formula to calculate the weighted average: (1*A + 2*B + 3*C) / (A+B+C)
 *    where A, B, C are the counts for ratings 1, 2, 3 respectively
 * 3. The seriesLetters (A, B, C...) are used as variables in the formula to reference each series
 */
function RatingScoreOverTime({
    questionIndex,
    questionId,
    scale,
}: {
    questionIndex: number
    questionId: string
    scale: 3 | 5 | 7
}): JSX.Element {
    const { dateRange, interval, compareFilter, defaultInterval, survey } = useValues(surveyLogic)
    const { setDateRange, setInterval, setCompareFilter } = useActions(surveyLogic)

    // Array to hold the event series - one series for each possible rating value
    const series: Array<{
        event: string
        kind: NodeKind.EventsNode
        custom_name: string
        properties: Array<{
            type: PropertyFilterType.HogQL
            key: string
        }>
    }> = []

    // Parts for building the weighted average formula
    const formulaNumeratorParts: string[] = [] // Will contain: ["1*A", "2*B", "3*C", ...]
    const formulaDenominatorParts: string[] = [] // Will contain: ["A", "B", "C", ...]

    // Letters used as variables in the formula to reference each series
    // A = first series (rating 1), B = second series (rating 2), etc.
    const seriesLetters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    // Create a series for each possible rating value (1 to scale)
    // For scale 3: creates series for ratings 1, 2, 3
    // For scale 5: creates series for ratings 1, 2, 3, 4, 5
    // For scale 7: creates series for ratings 1, 2, 3, 4, 5, 6, 7
    for (let i = 1; i <= scale; i++) {
        const ratingValue = i.toString()

        // Create a series that counts responses with this specific rating value
        series.push(createSingleRatingTrendSeries(ratingValue, questionIndex, questionId))

        // Get the corresponding letter for this series (A, B, C, ...)
        const seriesLetter = seriesLetters[i - 1]

        // Add to formula parts:
        // - Numerator: rating_value * series_count (e.g., "3*C" for rating 3)
        // - Denominator: just the series_count (e.g., "C")
        formulaNumeratorParts.push(`${i}*${seriesLetter}`)
        formulaDenominatorParts.push(seriesLetter)
    }

    // Build the weighted average formula
    // Example for scale 3: "(1*A + 2*B + 3*C) / (A+B+C)"
    // This calculates: (sum of rating_value * count_for_that_rating) / total_responses
    const formula = `(${formulaNumeratorParts.join('+')}) / (${formulaDenominatorParts.join('+')})`

    return (
        <div className="bg-surface-primary rounded">
            <LemonCollapse
                panels={[
                    {
                        key: 'average-rating-trend',
                        header: `Average Rating Trend Over Time`,
                        content: (
                            <div>
                                <div className="flex justify-between items-center p-2">
                                    <div className="flex gap-2 items-center">
                                        <DateFilter
                                            dateFrom={dateRange?.date_from ?? undefined}
                                            dateTo={dateRange?.date_to ?? undefined}
                                            onChange={(fromDate, toDate) =>
                                                setDateRange({
                                                    date_from: fromDate,
                                                    date_to: toDate,
                                                })
                                            }
                                        />
                                        <span>grouped by</span>
                                        <IntervalFilterStandalone
                                            interval={interval ?? defaultInterval}
                                            onIntervalChange={setInterval}
                                        />
                                        <CompareFilter
                                            compareFilter={compareFilter}
                                            updateCompareFilter={(compareFilter) => setCompareFilter(compareFilter)}
                                        />
                                    </div>
                                </div>
                                <Query
                                    query={{
                                        kind: NodeKind.InsightVizNode,
                                        source: {
                                            kind: NodeKind.TrendsQuery,
                                            interval: interval ?? defaultInterval,
                                            compareFilter: compareFilter,
                                            dateRange: dateRange ?? {
                                                date_from: dayjs((survey as Survey).created_at).format('YYYY-MM-DD'),
                                                date_to: survey.end_date
                                                    ? dayjs(survey.end_date).format('YYYY-MM-DD')
                                                    : dayjs().add(1, 'day').format('YYYY-MM-DD'),
                                            },
                                            series: series,
                                            properties: [
                                                {
                                                    type: PropertyFilterType.Event,
                                                    key: SurveyEventProperties.SURVEY_ID,
                                                    operator: PropertyOperator.Exact,
                                                    value: survey.id,
                                                },
                                            ],
                                            trendsFilter: {
                                                formula: formula,
                                                display: ChartDisplayType.ActionsBar,
                                            },
                                        },
                                    }}
                                    readOnly
                                />
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}

interface Props {
    question: RatingSurveyQuestion
    questionIndex: number
    processedData: ChoiceQuestionProcessedResponses
}

export function RatingQuestionViz({ question, questionIndex, processedData }: Props): JSX.Element | null {
    const barColor = CHART_INSIGHTS_COLORS[0]

    const { data } = processedData
    const npsBreakdown = calculateNpsBreakdownFromProcessedData(processedData)

    return (
        <>
            <div className="flex flex-col gap-1">
                <div className="h-50 border rounded pt-8">
                    <div className="relative h-full w-full">
                        <BindLogic logic={insightLogic} props={insightProps}>
                            <LineGraph
                                inSurveyView={true}
                                hideYAxis={true}
                                showValuesOnSeries={true}
                                labelGroupType={1}
                                data-attr="survey-rating"
                                type={GraphType.Bar}
                                hideAnnotations={true}
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
                                        data: data.map((d) => d.value),
                                        backgroundColor: barColor,
                                        borderColor: barColor,
                                        hoverBackgroundColor: barColor,
                                    },
                                ]}
                                labels={CHART_LABELS?.[question.scale] || ['1', '2', '3']}
                            />
                        </BindLogic>
                    </div>
                </div>
                <div className="flex flex-row justify-between">
                    <div className="text-secondary pl-10">{question.lowerBoundLabel}</div>
                    <div className="text-secondary pr-10">{question.upperBoundLabel}</div>
                </div>
            </div>
            {npsBreakdown && <NPSBreakdownViz npsBreakdown={npsBreakdown} />}
            {question.scale === 10 && (
                <NPSRatingOverTime questionIndex={questionIndex} questionId={question.id ?? ''} />
            )}
            {[3, 5, 7].includes(question.scale) && question.id && (
                <RatingScoreOverTime
                    questionIndex={questionIndex}
                    questionId={question.id}
                    scale={question.scale as 3 | 5 | 7}
                />
            )}
        </>
    )
}
