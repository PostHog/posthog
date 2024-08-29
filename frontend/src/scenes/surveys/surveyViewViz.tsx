import { IconInfo } from '@posthog/icons'
import { LemonTable } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { PieChart } from 'scenes/insights/views/LineGraph/PieChart'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { GraphType } from '~/types'
import { InsightLogicProps, SurveyQuestionType } from '~/types'

import {
    QuestionResultsReady,
    surveyLogic,
    SurveyMultipleChoiceResults,
    SurveyOpenTextResults,
    SurveyRatingResults,
    SurveyRecurringNPSResults,
    SurveySingleChoiceResults,
    SurveyUserStats,
} from './surveyLogic'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

const recurringNPSInsightProps: InsightLogicProps = {
    dashboardItemId: `new-survey-recurring-nps`,
}

const formatCount = (count: number, total: number): string => {
    if ((count / total) * 100 < 3) {
        return ''
    }
    return `${humanFriendlyNumber(count)}`
}

export function UsersCount({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { seen, dismissed, sent } = surveyUserStats
    const total = seen + dismissed + sent
    const labelTotal = total === 1 ? 'Unique user shown' : 'Unique users shown'
    const labelSent = sent === 1 ? 'Response sent' : 'Responses sent'

    return (
        <div className="inline-flex mb-4">
            <div>
                <div className="text-4xl font-bold">{humanFriendlyNumber(total)}</div>
                <div className="font-semibold text-muted-alt">{labelTotal}</div>
            </div>
            {sent > 0 && (
                <div className="ml-10">
                    <div className="text-4xl font-bold">{humanFriendlyNumber(sent)}</div>
                    <div className="font-semibold text-muted-alt">{labelSent}</div>
                </div>
            )}
        </div>
    )
}

export function UsersStackedBar({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { seen, dismissed, sent } = surveyUserStats

    const total = seen + dismissed + sent
    const seenPercentage = (seen / total) * 100
    const dismissedPercentage = (dismissed / total) * 100
    const sentPercentage = (sent / total) * 100

    return (
        <>
            {total > 0 && (
                <div className="mb-8">
                    <div className="relative w-full mx-auto h-10 mb-4">
                        {[
                            {
                                count: seen,
                                label: 'Shown',
                                classes: `rounded-l ${dismissed === 0 && sent === 0 ? 'rounded-r' : ''}`,
                                style: { backgroundColor: '#1D4AFF', width: `${seenPercentage}%` },
                            },
                            {
                                count: dismissed,
                                label: 'Dismissed',
                                classes: `${seen === 0 ? 'rounded-l' : ''} ${sent === 0 ? 'rounded-r' : ''}`,
                                style: {
                                    backgroundColor: '#E3A506',
                                    width: `${dismissedPercentage}%`,
                                    left: `${seenPercentage}%`,
                                },
                            },
                            {
                                count: sent,
                                label: 'Sent',
                                classes: `rounded-r ${seen === 0 && dismissed === 0 ? 'rounded-l' : ''}`,
                                style: {
                                    backgroundColor: '#529B08',
                                    width: `${sentPercentage}%`,
                                    left: `${seenPercentage + dismissedPercentage}%`,
                                },
                            },
                        ].map(({ count, label, classes, style }) => (
                            <Tooltip
                                key={`survey-summary-chart-${label}`}
                                title={`${label} surveys: ${count}`}
                                delayMs={0}
                                placement="top"
                            >
                                <div
                                    className={`h-10 text-white text-center absolute cursor-pointer ${classes}`}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={style}
                                >
                                    <span className="inline-flex font-semibold max-w-full px-1 truncate leading-10">
                                        {formatCount(count, total)}
                                    </span>
                                </div>
                            </Tooltip>
                        ))}
                    </div>
                    <div className="w-full flex justify-center">
                        <div className="flex items-center">
                            {[
                                { count: seen, label: 'Viewed', style: { backgroundColor: '#1D4AFF' } },
                                { count: dismissed, label: 'Dismissed', style: { backgroundColor: '#E3A506' } },
                                { count: sent, label: 'Submitted', style: { backgroundColor: '#529B08' } },
                            ].map(
                                ({ count, label, style }) =>
                                    count > 0 && (
                                        <div key={`survey-summary-legend-${label}`} className="flex items-center mr-6">
                                            {/* eslint-disable-next-line react/forbid-dom-props */}
                                            <div className="w-3 h-3 rounded-full mr-2" style={style} />
                                            <span className="font-semibold text-muted-alt">{`${label} (${(
                                                (count / total) *
                                                100
                                            ).toFixed(1)}%)`}</span>
                                        </div>
                                    )
                            )}
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}

export function Summary({
    surveyUserStats,
    surveyUserStatsLoading,
}: {
    surveyUserStats: SurveyUserStats
    surveyUserStatsLoading: boolean
}): JSX.Element {
    return (
        <div className="mb-4 mt-2">
            {surveyUserStatsLoading ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : (
                <>
                    {!surveyUserStats ? null : (
                        <>
                            <UsersCount surveyUserStats={surveyUserStats} />
                            <UsersStackedBar surveyUserStats={surveyUserStats} />
                        </>
                    )}
                </>
            )}
        </div>
    )
}

export function RatingQuestionBarChart({
    questionIndex,
    surveyRatingResults,
    surveyRatingResultsReady,
    iteration,
}: {
    questionIndex: number
    surveyRatingResults: SurveyRatingResults
    surveyRatingResultsReady: QuestionResultsReady
    iteration?: number | null | undefined
}): JSX.Element {
    const { loadSurveyRatingResults } = useActions(surveyLogic)
    const { survey } = useValues(surveyLogic)
    const barColor = '#1d4aff'
    const question = survey.questions[questionIndex]
    if (question.type !== SurveyQuestionType.Rating) {
        throw new Error(`Question type must be ${SurveyQuestionType.Rating}`)
    }
    useEffect(() => {
        loadSurveyRatingResults({ questionIndex, iteration })
    }, [questionIndex])

    return (
        <div className="mb-4">
            {!surveyRatingResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveyRatingResults[questionIndex]?.total ? (
                <></>
            ) : (
                <div className="mb-8">
                    <div className="font-semibold text-muted-alt">{`${
                        question.scale === 10 ? '0 - 10' : '1 - 5'
                    } rating`}</div>
                    <div className="text-xl font-bold mb-2">{question.question}</div>
                    <div className=" h-50 border rounded pt-8">
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
                                            data: surveyRatingResults[questionIndex].data,
                                            backgroundColor: barColor,
                                            borderColor: barColor,
                                            hoverBackgroundColor: barColor,
                                        },
                                    ]}
                                    labels={
                                        question.scale === 10
                                            ? ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10']
                                            : ['1', '2', '3', '4', '5']
                                    }
                                />
                            </BindLogic>
                        </div>
                    </div>
                    <div className="flex flex-row justify-between mt-1">
                        <div className="text-muted-alt pl-10">{question.lowerBoundLabel}</div>
                        <div className="text-muted-alt pr-10">{question.upperBoundLabel}</div>
                    </div>
                </div>
            )}
        </div>
    )
}

export function NPSSurveyResultsBarChart({
    questionIndex,
    surveyRecurringNPSResults,
    surveyRecurringNPSResultsReady,
    iterationStartDates,
    currentIteration,
}: {
    questionIndex: number
    surveyRecurringNPSResults: SurveyRecurringNPSResults
    surveyRecurringNPSResultsReady: QuestionResultsReady
    iterationStartDates: string[]
    currentIteration: number
}): JSX.Element {
    const { loadSurveyRecurringNPSResults } = useActions(surveyLogic)
    const { survey } = useValues(surveyLogic)
    const barColor = '#1d4aff'
    const question = survey.questions[questionIndex]
    if (question.type !== SurveyQuestionType.Rating) {
        throw new Error(`Question type must be ${SurveyQuestionType.Rating}`)
    }

    useEffect(() => {
        loadSurveyRecurringNPSResults({ questionIndex })
    }, [questionIndex])

    return (
        <div className="mb-4">
            {!surveyRecurringNPSResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveyRecurringNPSResults[questionIndex]?.total ? (
                <></>
            ) : (
                <div className="mb-8">
                    <div className="font-semibold text-muted-alt">{`${
                        question.scale === 10 ? '0 - 10' : '1 - 5'
                    } rating`}</div>
                    <div className="text-xl font-bold mb-2">NPS Scores over time for "{question.question}"</div>
                    <div className=" h-50 border rounded pt-8">
                        <div className="relative h-full w-full">
                            <BindLogic logic={insightLogic} props={recurringNPSInsightProps}>
                                <LineGraph
                                    inSurveyView={true}
                                    hideYAxis={true}
                                    showValuesOnSeries={true}
                                    labelGroupType="none"
                                    data-attr="survey-rating"
                                    type={GraphType.Line}
                                    hideAnnotations={false}
                                    formula="-"
                                    tooltip={{
                                        showHeader: true,
                                        hideColorCol: true,
                                    }}
                                    trendsFilter={{
                                        showLegend: true,
                                    }}
                                    datasets={[
                                        {
                                            id: 1,
                                            label: 'NPS Score',
                                            barPercentage: 0.8,
                                            minBarLength: 2,
                                            data: surveyRecurringNPSResults[questionIndex].data,
                                            backgroundColor: barColor,
                                            borderColor: barColor,
                                            hoverBackgroundColor: barColor,
                                        },
                                    ]}
                                    labels={iterationStartDates
                                        .slice(0, currentIteration)
                                        .map((sd) => dayjs(sd).format('YYYY-MM-DD'))}
                                />
                            </BindLogic>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export function SingleChoiceQuestionPieChart({
    questionIndex,
    surveySingleChoiceResults,
    surveySingleChoiceResultsReady,
}: {
    questionIndex: number
    surveySingleChoiceResults: SurveySingleChoiceResults
    surveySingleChoiceResultsReady: QuestionResultsReady
}): JSX.Element {
    const { loadSurveySingleChoiceResults } = useActions(surveyLogic)
    const { survey } = useValues(surveyLogic)

    const question = survey.questions[questionIndex]
    if (question.type !== SurveyQuestionType.SingleChoice) {
        throw new Error(`Question type must be ${SurveyQuestionType.SingleChoice}`)
    }

    // Insights colors
    // TODO: make available in Tailwind
    const colors = [
        '#1D4BFF',
        '#CD0F74',
        '#43827E',
        '#621DA6',
        '#F04F58',
        '#539B0A',
        '#E3A605',
        '#0476FB',
        '#36416B',
        '#41CBC3',
        '#A46FFF',
        '#FE729E',
        '#CE1175',
        '#B64B01',
    ]

    useEffect(() => {
        loadSurveySingleChoiceResults({ questionIndex })
    }, [questionIndex])

    return (
        <div className="mb-4">
            {!surveySingleChoiceResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveySingleChoiceResults[questionIndex]?.data.length ? (
                <></>
            ) : (
                <div className="mb-8">
                    <div className="font-semibold text-muted-alt">Single choice</div>
                    <div className="text-xl font-bold mb-2">{question.question}</div>
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
                                            data: surveySingleChoiceResults[questionIndex].data,
                                            labels: surveySingleChoiceResults[questionIndex].labels,
                                            backgroundColor: surveySingleChoiceResults[questionIndex].labels.map(
                                                (_: string, i: number) => colors[i % colors.length]
                                            ),
                                        },
                                    ]}
                                    labels={surveySingleChoiceResults[questionIndex].labels}
                                />
                            </BindLogic>
                        </div>
                        <div
                            className={`grid h-full pl-4 ${(() => {
                                const dataLength = surveySingleChoiceResults[questionIndex].data.length
                                // We need to return the whole class for Tailwind to see them when scanning code
                                if (dataLength < 5) {
                                    return 'py-20'
                                } else if (dataLength < 7) {
                                    return 'py-15'
                                } else if (dataLength < 10) {
                                    return 'py-10'
                                }
                                return 'py-5'
                            })()} grid-cols-${Math.ceil(surveySingleChoiceResults[questionIndex].data.length / 10)}`}
                        >
                            {surveySingleChoiceResults[questionIndex].data.map((count: number, i: number) => {
                                const { total, labels } = surveySingleChoiceResults[questionIndex]
                                const percentage = ((count / total) * 100).toFixed(1)

                                return (
                                    <div
                                        key={`single-choice-legend-${questionIndex}-${i}`}
                                        className="flex items-center mr-6"
                                    >
                                        <div
                                            className="w-3 h-3 rounded-full mr-2"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ backgroundColor: colors[i % colors.length] }}
                                        />
                                        <span className="font-semibold text-muted-alt max-w-48 truncate">{`${labels[i]}`}</span>
                                        <span className="font-bold ml-1 truncate">{` ${percentage}% `}</span>
                                        <span className="font-semibold text-muted-alt ml-1 truncate">{`(${count})`}</span>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export function MultipleChoiceQuestionBarChart({
    questionIndex,
    surveyMultipleChoiceResults,
    surveyMultipleChoiceResultsReady,
}: {
    questionIndex: number
    surveyMultipleChoiceResults: SurveyMultipleChoiceResults
    surveyMultipleChoiceResultsReady: QuestionResultsReady
}): JSX.Element {
    const { loadSurveyMultipleChoiceResults } = useActions(surveyLogic)
    const { survey } = useValues(surveyLogic)
    const [chartHeight, setChartHeight] = useState(200)
    const barColor = '#1d4aff'

    const question = survey.questions[questionIndex]
    if (question.type !== SurveyQuestionType.MultipleChoice) {
        throw new Error(`Question type must be ${SurveyQuestionType.MultipleChoice}`)
    }

    useEffect(() => {
        loadSurveyMultipleChoiceResults({ questionIndex })
    }, [questionIndex])

    useEffect(() => {
        if (surveyMultipleChoiceResults?.[questionIndex]?.data?.length) {
            setChartHeight(100 + 20 * surveyMultipleChoiceResults[questionIndex].data.length)
        }
    }, [surveyMultipleChoiceResults])

    return (
        <div className="mb-4">
            {!surveyMultipleChoiceResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveyMultipleChoiceResults[questionIndex]?.data.length ? (
                <></>
            ) : (
                <div className="mb-8">
                    <div className="font-semibold text-muted-alt">Multiple choice</div>
                    <div className="text-xl font-bold mb-2">{question.question}</div>

                    <div
                        className="border rounded pt-6 pr-10"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: Math.min(chartHeight, 600) }}
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
                                        data: surveyMultipleChoiceResults[questionIndex].data,
                                        labels: surveyMultipleChoiceResults[questionIndex].labels,
                                        breakdownValues: surveyMultipleChoiceResults[questionIndex].labels,
                                        backgroundColor: barColor,
                                        borderColor: barColor,
                                        hoverBackgroundColor: barColor,
                                    },
                                ]}
                                labels={surveyMultipleChoiceResults[questionIndex].labels}
                            />
                        </BindLogic>
                    </div>
                </div>
            )}
        </div>
    )
}

export function OpenTextViz({
    questionIndex,
    surveyOpenTextResults,
    surveyOpenTextResultsReady,
}: {
    questionIndex: number
    surveyOpenTextResults: SurveyOpenTextResults
    surveyOpenTextResultsReady: QuestionResultsReady
}): JSX.Element {
    const { loadSurveyOpenTextResults } = useActions(surveyLogic)
    const { survey } = useValues(surveyLogic)
    const surveyResponseField = questionIndex === 0 ? '$survey_response' : `$survey_response_${questionIndex}`

    const question = survey.questions[questionIndex]
    if (question.type !== SurveyQuestionType.Open) {
        throw new Error(`Question type must be ${SurveyQuestionType.Open}`)
    }

    useEffect(() => {
        loadSurveyOpenTextResults({ questionIndex })
    }, [questionIndex])

    return (
        <div className="mb-4">
            {!surveyOpenTextResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveyOpenTextResults[questionIndex]?.events.length ? (
                <></>
            ) : (
                <>
                    <Tooltip title="See all Open Text responses in the Events table at the bottom.">
                        <div className="inline-flex gap-1">
                            <div className="font-semibold text-muted-alt">Open text</div>
                            <LemonDivider vertical className="my-1 mx-1" />
                            <div className="font-semibold text-muted-alt">random selection</div>
                            <IconInfo className="text-lg text-muted-alt shrink-0 ml-0.5 mt-0.5" />
                        </div>
                    </Tooltip>
                    <div className="text-xl font-bold mb-4">{question.question}</div>
                    <div className="mt-4 mb-8 masonry-container">
                        {surveyOpenTextResults[questionIndex].events.map((event, i) => {
                            const personProp = {
                                distinct_id: event.distinct_id,
                                properties: event.personProperties,
                            }

                            return (
                                <div key={`open-text-${questionIndex}-${i}`} className="masonry-item border rounded">
                                    <div className="max-h-80 overflow-y-auto text-center italic font-semibold px-5 py-4">
                                        {typeof event.properties[surveyResponseField] !== 'string'
                                            ? JSON.stringify(event.properties[surveyResponseField])
                                            : event.properties[surveyResponseField]}
                                    </div>
                                    <div className="bg-bg-light items-center px-5 py-4 border-t rounded-b truncate w-full">
                                        <PersonDisplay
                                            person={personProp}
                                            withIcon={true}
                                            noEllipsis={false}
                                            isCentered
                                        />
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </>
            )}
        </div>
    )
}
