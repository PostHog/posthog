import {
    IconInfo,
    IconSparkles,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
} from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { PieChart } from 'scenes/insights/views/LineGraph/PieChart'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { NPS_DETRACTOR_LABEL, NPS_PASSIVE_LABEL, NPS_PROMOTER_LABEL } from 'scenes/surveys/constants'
import { getSurveyResponseKey, NPSBreakdown } from 'scenes/surveys/utils'

import { GraphType, InsightLogicProps, SurveyQuestionType } from '~/types'

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

// Define a type for the color classes to ensure type safety
type ColorClass = 'bg-brand-blue' | 'bg-warning' | 'bg-success' | 'bg-danger'

type StackedBarSegment = {
    count: number
    label: string
    colorClass: ColorClass
}

function StackedBar({ segments }: { segments: StackedBarSegment[] }): JSX.Element {
    const total = segments.reduce((sum, segment) => sum + segment.count, 0)
    let accumulatedPercentage = 0

    return (
        <>
            {total > 0 && (
                <div>
                    <div className="relative w-full mx-auto h-10 mb-4">
                        {segments.map(({ count, label, colorClass }, index) => {
                            const percentage = (count / total) * 100
                            const left = accumulatedPercentage
                            accumulatedPercentage += percentage

                            const isFirst = index === 0
                            const isLast = index === segments.length - 1
                            const isOnly = segments.length === 1

                            return (
                                <Tooltip
                                    key={`stacked-bar-${label}`}
                                    title={`${label}: ${count} (${percentage.toFixed(1)}%)`}
                                    delayMs={0}
                                    placement="top"
                                >
                                    <div
                                        className={clsx(
                                            'h-10 text-white text-center absolute cursor-pointer',
                                            colorClass,
                                            isFirst || isOnly ? 'rounded-l' : '',
                                            isLast || isOnly ? 'rounded-r' : ''
                                        )}
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            width: `${percentage}%`,
                                            left: `${left}%`,
                                        }}
                                    >
                                        <span className="inline-flex font-semibold max-w-full px-1 truncate leading-10">
                                            {formatCount(count, total)}
                                        </span>
                                    </div>
                                </Tooltip>
                            )
                        })}
                    </div>
                    <div className="w-full flex justify-center">
                        <div className="flex items-center">
                            {segments.map(
                                ({ count, label, colorClass }) =>
                                    count > 0 && (
                                        <div key={`stacked-bar-legend-${label}`} className="flex items-center mr-6">
                                            <div className={clsx('w-3 h-3 rounded-full mr-2', colorClass)} />
                                            <span className="font-semibold text-secondary">{`${label} (${(
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

export function UsersCount({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { seen, dismissed, sent } = surveyUserStats
    const total = seen + dismissed + sent

    return (
        <div className="inline-flex mb-4">
            <div>
                <div className="text-4xl font-bold">{humanFriendlyNumber(total)}</div>
                <div className="font-semibold text-secondary">Unique user(s) shown</div>
            </div>
            {sent > 0 && (
                <div className="ml-10">
                    <div className="text-4xl font-bold">{humanFriendlyNumber(sent)}</div>
                    <div className="font-semibold text-secondary">Response(s) sent</div>
                </div>
            )}
        </div>
    )
}

export function UsersStackedBar({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { seen, dismissed, sent } = surveyUserStats

    const segments: StackedBarSegment[] = [
        { count: seen, label: 'Unanswered', colorClass: 'bg-brand-blue' },
        { count: dismissed, label: 'Dismissed', colorClass: 'bg-warning' },
        { count: sent, label: 'Submitted', colorClass: 'bg-success' },
    ]

    return <StackedBar segments={segments} />
}

export function NPSStackedBar({ npsBreakdown }: { npsBreakdown: NPSBreakdown }): JSX.Element {
    const segments: StackedBarSegment[] = [
        { count: npsBreakdown.detractors, label: NPS_DETRACTOR_LABEL, colorClass: 'bg-danger' },
        { count: npsBreakdown.passives, label: NPS_PASSIVE_LABEL, colorClass: 'bg-warning' },
        { count: npsBreakdown.promoters, label: NPS_PROMOTER_LABEL, colorClass: 'bg-success' },
    ]

    return <StackedBar segments={segments} />
}

export function Summary({
    surveyUserStats,
    surveyUserStatsLoading,
}: {
    surveyUserStats: SurveyUserStats
    surveyUserStatsLoading: boolean
}): JSX.Element {
    return (
        <div>
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
    useEffect(() => {
        loadSurveyRatingResults({ questionIndex })
    }, [questionIndex, loadSurveyRatingResults])
    if (question.type !== SurveyQuestionType.Rating) {
        throw new Error(`Question type must be ${SurveyQuestionType.Rating}`)
    }

    return (
        <div>
            {!surveyRatingResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveyRatingResults[questionIndex]?.total ? (
                <></>
            ) : (
                <div>
                    <div className="font-semibold text-secondary">{`${
                        question.scale === 10
                            ? '0 - 10'
                            : question.scale === 7
                            ? '1 - 7'
                            : question.scale === 5
                            ? '1 - 5'
                            : '1 - 3'
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
                                            : question.scale === 7
                                            ? ['1', '2', '3', '4', '5', '6', '7']
                                            : question.scale === 5
                                            ? ['1', '2', '3', '4', '5']
                                            : ['1', '2', '3']
                                    }
                                />
                            </BindLogic>
                        </div>
                    </div>
                    <div className="flex flex-row justify-between mt-1">
                        <div className="text-secondary pl-10">{question.lowerBoundLabel}</div>
                        <div className="text-secondary pr-10">{question.upperBoundLabel}</div>
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
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [questionIndex])

    return (
        <div>
            {!surveyRecurringNPSResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveyRecurringNPSResults[questionIndex]?.total ? (
                <></>
            ) : (
                <div>
                    <div className="font-semibold text-secondary">{`${
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
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [questionIndex])

    return (
        <div>
            {!surveySingleChoiceResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveySingleChoiceResults[questionIndex]?.data.length ? (
                <></>
            ) : (
                <div>
                    <div className="font-semibold text-secondary">Single choice</div>
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
                                        <span className="font-semibold text-secondary max-w-48 truncate">{`${labels[i]}`}</span>
                                        <span className="font-bold ml-1 truncate">{` ${percentage}% `}</span>
                                        <span className="font-semibold text-secondary ml-1 truncate">{`(${count})`}</span>
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
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [questionIndex])

    useEffect(() => {
        if (surveyMultipleChoiceResults?.[questionIndex]?.data?.length) {
            setChartHeight(100 + 20 * surveyMultipleChoiceResults[questionIndex].data.length)
        }
        // TODO this one maybe should have questionIndex as a dependency
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [surveyMultipleChoiceResults])

    return (
        <div>
            {!surveyMultipleChoiceResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveyMultipleChoiceResults[questionIndex]?.data.length ? (
                <></>
            ) : (
                <div className="mb-8">
                    <div className="font-semibold text-secondary">Multiple choice</div>
                    <div className="text-xl font-bold mb-2">{question.question}</div>

                    <div
                        className="border rounded pt-8 pr-10 overflow-y-scroll"
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
    const surveyResponseKey = getSurveyResponseKey(questionIndex)

    const question = survey.questions[questionIndex]
    if (question.type !== SurveyQuestionType.Open) {
        throw new Error(`Question type must be ${SurveyQuestionType.Open}`)
    }

    useEffect(() => {
        loadSurveyOpenTextResults({ questionIndex })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [questionIndex])

    return (
        <div>
            {!surveyOpenTextResultsReady[questionIndex] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : !surveyOpenTextResults[questionIndex]?.events.length ? (
                <></>
            ) : (
                <>
                    <div className="flex flex-row justify-between items-center">
                        <Tooltip title="See all Open Text responses in the Events table at the bottom.">
                            <div className="inline-flex gap-1">
                                <div className="font-semibold text-secondary">Open text</div>
                                <LemonDivider vertical className="my-1 mx-1" />
                                <div className="font-semibold text-secondary">random selection</div>
                                <IconInfo className="text-lg text-secondary shrink-0 ml-0.5 mt-0.5" />
                            </div>
                        </Tooltip>
                        <ResponseSummariesButton questionIndex={questionIndex} />
                    </div>
                    <div className="text-xl font-bold mb-4">{question.question}</div>
                    <ResponseSummariesDisplay />
                    <div className="mt-4 mb-8 masonry-container">
                        {surveyOpenTextResults[questionIndex].events.map((event, i) => {
                            const personProp = {
                                distinct_id: event.distinct_id,
                                properties: event.personProperties,
                            }

                            return (
                                <div key={`open-text-${questionIndex}-${i}`} className="masonry-item border rounded">
                                    <div className="max-h-80 overflow-y-auto text-center italic font-semibold px-5 py-4">
                                        {typeof event.properties[surveyResponseKey] !== 'string'
                                            ? JSON.stringify(event.properties[surveyResponseKey])
                                            : event.properties[surveyResponseKey]}
                                    </div>
                                    <div className="bg-surface-primary items-center px-5 py-4 border-t rounded-b truncate w-full">
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

function ResponseSummariesButton({ questionIndex }: { questionIndex: number | undefined }): JSX.Element {
    const { summarize } = useActions(surveyLogic)
    const { responseSummary, responseSummaryLoading } = useValues(surveyLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.AI_SURVEY_RESPONSE_SUMMARY} match={true}>
            <AIConsentPopoverWrapper showArrow>
                <LemonButton
                    type="secondary"
                    data-attr="summarize-survey"
                    onClick={() => summarize({ questionIndex })}
                    disabledReason={
                        !dataProcessingAccepted
                            ? dataProcessingApprovalDisabledReason || 'Data processing not accepted'
                            : responseSummaryLoading
                            ? 'Let me think...'
                            : responseSummary
                            ? 'Already summarized'
                            : undefined
                    }
                    icon={<IconSparkles />}
                    loading={responseSummaryLoading}
                >
                    {responseSummaryLoading ? 'Let me think...' : 'Summarize responses'}
                </LemonButton>
            </AIConsentPopoverWrapper>
        </FlaggedFeature>
    )
}

function ResponseSummariesDisplay(): JSX.Element {
    const { survey, responseSummary } = useValues(surveyLogic)

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.AI_SURVEY_RESPONSE_SUMMARY} match={true}>
            {responseSummary ? (
                <>
                    <h1>Responses summary</h1>
                    <LemonMarkdown>{responseSummary.content}</LemonMarkdown>
                    <LemonDivider dashed={true} />
                    <ResponseSummaryFeedback surveyId={survey.id} />
                </>
            ) : null}
        </FlaggedFeature>
    )
}

function ResponseSummaryFeedback({ surveyId }: { surveyId: string }): JSX.Element {
    const [rating, setRating] = useState<'good' | 'bad' | null>(null)

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating) {
            return // Already rated
        }
        setRating(newRating)
        posthog.capture('ai_survey_summary_rated', {
            survey_id: surveyId,
            answer_rating: newRating,
        })
    }

    return (
        <div className="flex items-center justify-end">
            {rating === null ? <>Summaries are generated by AI. What did you think?</> : null}
            {rating !== 'bad' && (
                <LemonButton
                    icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                    type="tertiary"
                    size="small"
                    tooltip="Good summary"
                    onClick={() => submitRating('good')}
                />
            )}
            {rating !== 'good' && (
                <LemonButton
                    icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                    type="tertiary"
                    size="small"
                    tooltip="Bad summary"
                    onClick={() => submitRating('bad')}
                />
            )}
        </div>
    )
}
