import { LemonTable } from '@posthog/lemon-ui'
import { surveyLogic, SurveyRatingResults, SurveyRatingResultsReady, SurveyUserStats } from './surveyLogic'
import { useActions, BindLogic } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { GraphType } from '~/types'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, RatingSurveyQuestion } from '~/types'
import { useEffect } from 'react'

const insightProps: InsightLogicProps = {
    dashboardItemId: `new-survey`,
}

const formatCount = (count: number, total: number): string => {
    if ((count / total) * 100 < 3) {
        return ''
    }
    return `${count}`
}

export function UsersCount({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { seen, dismissed, sent } = surveyUserStats
    const total = seen + dismissed + sent
    const labelTotal = total === 1 ? 'Unique user viewed' : 'Unique users viewed'
    const labelSent = sent === 1 ? 'Response submitted' : 'Responses submitted'

    return (
        <div className="inline-flex mb-4">
            <div>
                <div className="text-4xl font-bold">{total}</div>
                <div className="font-semibold text-muted-alt">{labelTotal}</div>
            </div>
            {sent > 0 && (
                <div className="ml-10">
                    <div className="text-4xl font-bold">{sent}</div>
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
                <div className="mb-6">
                    <div className="w-full mx-auto h-10 mb-4">
                        {[
                            {
                                count: seen,
                                label: 'Viewed',
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
                                label: 'Submitted',
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
                            ].map(({ count, label, style }) => (
                                <div key={`survey-summary-legend-${label}`} className="flex items-center mr-6">
                                    <div className="w-3 h-3 rounded-full mr-2" style={style} />
                                    <span className="font-semibold text-muted-alt">{`${label} (${(
                                        (count / total) *
                                        100
                                    ).toFixed(1)}%)`}</span>
                                </div>
                            ))}
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
    question,
    surveyRatingResults,
    surveyRatingResultsReady,
}: {
    questionIndex: number
    question: RatingSurveyQuestion
    surveyRatingResults: SurveyRatingResults
    surveyRatingResultsReady: SurveyRatingResultsReady
}): JSX.Element {
    const { loadSurveyRatingResults } = useActions(surveyLogic)

    useEffect(() => {
        loadSurveyRatingResults({ questionIndex, question })
    }, [question])

    return (
        <div className="mb-4">
            {!surveyRatingResultsReady[`question_${questionIndex}`] ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : (
                <div className="mb-8">
                    <div className="font-semibold text-muted-alt">{`1-${question.scale} rating`}</div>
                    <div className="text-xl font-bold mb-2">{question.question}</div>
                    <div className=" h-50 border rounded pt-6 pb-2 px-2">
                        <div className="relative h-full w-full">
                            <BindLogic logic={insightLogic} props={insightProps}>
                                <LineGraph
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
                                            barPercentage: 0.7,
                                            minBarLength: 2,
                                            data: surveyRatingResults[`question_${questionIndex}`],
                                            backgroundColor: '#1d4aff',
                                            hoverBackgroundColor: '#1d4aff',
                                        },
                                    ]}
                                    labels={Array.from({ length: question.scale }, (_, i) => (i + 1).toString()).map(
                                        (n) => n
                                    )}
                                />
                            </BindLogic>
                        </div>
                    </div>
                    <div className="flex flex-row justify-between mt-1">
                        <div className="text-muted-alt">{question.lowerBoundLabel}</div>
                        <div className="text-muted-alt">{question.upperBoundLabel}</div>
                    </div>
                </div>
            )}
        </div>
    )
}
