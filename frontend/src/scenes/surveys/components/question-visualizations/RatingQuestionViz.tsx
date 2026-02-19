import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconInfo, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IntervalFilterStandalone } from 'lib/components/IntervalFilter'
import { dayjs } from 'lib/dayjs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { hexToRGBA } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { StackedBar, StackedBarSegment, StackedBarSkeleton } from 'scenes/surveys/components/StackedBar'
import { CHART_INSIGHTS_COLORS } from 'scenes/surveys/components/question-visualizations/util'
import {
    NPS_DETRACTOR_LABEL,
    NPS_DETRACTOR_VALUES,
    NPS_PASSIVE_LABEL,
    NPS_PASSIVE_VALUES,
    NPS_PROMOTER_LABEL,
    NPS_PROMOTER_VALUES,
} from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import {
    NPSBreakdown,
    calculateNpsBreakdownFromProcessedData,
    getSurveyIdBasedResponseKey,
    isThumbQuestion,
} from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import {
    ChartDisplayType,
    ChoiceQuestionProcessedResponses,
    EventPropertyFilter,
    GraphPointPayload,
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

type NPSBucket = 'promoter' | 'passive' | 'detractor'

const NPS_BUCKET_COLORS: Record<NPSBucket, string> = {
    promoter: CHART_INSIGHTS_COLORS[5],
    passive: CHART_INSIGHTS_COLORS[6],
    detractor: CHART_INSIGHTS_COLORS[4],
}

const NPS_BUCKET_TEXT_CLASS: Record<NPSBucket, string> = {
    promoter: 'text-success',
    passive: 'text-warning',
    detractor: 'text-danger',
}

function getNpsBucketByRatingLabel(ratingLabel: string): { bucket: NPSBucket; label: string } {
    if (NPS_PROMOTER_VALUES.includes(ratingLabel)) {
        return { bucket: 'promoter', label: NPS_PROMOTER_LABEL }
    }

    if (NPS_PASSIVE_VALUES.includes(ratingLabel)) {
        return { bucket: 'passive', label: NPS_PASSIVE_LABEL }
    }

    return { bucket: 'detractor', label: NPS_DETRACTOR_LABEL }
}

function NPSStackedBar({ npsBreakdown }: { npsBreakdown: NPSBreakdown }): JSX.Element {
    const formatNpsBarValue = (count: number, total: number): string => {
        const percentage = (count / total) * 100
        if (percentage < 3) {
            return ''
        }
        return `${count} (${percentage.toFixed(1)}%)`
    }

    const segments: StackedBarSegment[] = [
        { count: npsBreakdown.detractors, label: NPS_DETRACTOR_LABEL, colorClass: 'bg-danger' },
        { count: npsBreakdown.passives, label: NPS_PASSIVE_LABEL, colorClass: 'bg-warning' },
        { count: npsBreakdown.promoters, label: NPS_PROMOTER_LABEL, colorClass: 'bg-success' },
    ]

    return <StackedBar segments={segments} showTooltips={false} barValueFormatter={formatNpsBarValue} />
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
    const score = Number(npsBreakdown.score)
    const formattedScore = Number.isInteger(score) ? String(score) : score.toFixed(1)

    return (
        <div className="flex flex-col gap-2">
            <div className="font-semibold text-secondary">
                <div className="text-4xl font-bold text-primary">{formattedScore}</div>
                <div className="text-sm text-muted mt-1">Latest NPS score (% promoters - % detractors)</div>
            </div>
            {npsBreakdown && <NPSStackedBar npsBreakdown={npsBreakdown} />}
        </div>
    )
}

interface ThumbsBreakdown {
    thumbsUp: number
    thumbsDown: number
}

function calculateThumbsBreakdown(processedData: ChoiceQuestionProcessedResponses): ThumbsBreakdown | null {
    if (!processedData?.data || processedData.data.length !== 2) {
        return null
    }

    const thumbsUp = processedData.data[0]?.value ?? 0
    const thumbsDown = processedData.data[1]?.value ?? 0

    return thumbsUp + thumbsDown > 0 ? { thumbsUp, thumbsDown } : null
}

function ThumbsBreakdownViz({ thumbsBreakdown }: { thumbsBreakdown: ThumbsBreakdown }): JSX.Element {
    const total = thumbsBreakdown.thumbsUp + thumbsBreakdown.thumbsDown
    const items = [
        {
            icon: IconThumbsUp,
            count: thumbsBreakdown.thumbsUp,
            label: 'Positive',
            bgClass: 'bg-brand-blue/10',
            textClass: 'text-brand-blue',
            barClass: 'bg-brand-blue',
        },
        {
            icon: IconThumbsDown,
            count: thumbsBreakdown.thumbsDown,
            label: 'Negative',
            bgClass: 'bg-warning/10',
            textClass: 'text-warning',
            barClass: 'bg-warning',
        },
    ]

    return (
        <div className="flex gap-3">
            {items.map(({ icon: Icon, count, label, bgClass, textClass, barClass }) => {
                const percent = (count / total) * 100
                return (
                    <div key={label} className="flex-1 p-4 border rounded bg-bg-light">
                        <div className="flex items-center gap-3">
                            <div className={`flex items-center justify-center size-10 rounded-full ${bgClass}`}>
                                <Icon className={`${textClass} size-5`} />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="flex items-baseline gap-2">
                                    <span className="text-2xl font-bold tabular-nums">{percent.toFixed(1)}%</span>
                                    <span className="text-secondary text-sm">({count})</span>
                                </div>
                                <div className="text-secondary text-xs font-medium">{label}</div>
                            </div>
                        </div>
                        <div className="mt-3 h-1.5 bg-border-light rounded-full overflow-hidden">
                            <div
                                className={`h-full ${barClass} rounded-full transition-all duration-300`}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ width: `${percent}%` }}
                            />
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

function NPSRatingOverTime({ questionIndex, questionId }: { questionIndex: number; questionId: string }): JSX.Element {
    const { dateRange, interval, compareFilter, defaultInterval, survey, archivedResponsesPropertyFilter } =
        useValues(surveyLogic)
    const { setDateRange, setInterval, setCompareFilter } = useActions(surveyLogic)

    const trendsQuery: TrendsQuery = {
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
            createNPSTrendSeries(NPS_PROMOTER_VALUES, NPS_PROMOTER_LABEL, questionIndex, questionId),
            createNPSTrendSeries(NPS_PASSIVE_VALUES, NPS_PASSIVE_LABEL, questionIndex, questionId),
            createNPSTrendSeries(NPS_DETRACTOR_VALUES, NPS_DETRACTOR_LABEL, questionIndex, questionId),
        ],
        properties: [
            {
                type: PropertyFilterType.Event,
                key: SurveyEventProperties.SURVEY_ID,
                operator: PropertyOperator.Exact,
                value: survey.id,
            },
            ...archivedResponsesPropertyFilter,
        ],
        trendsFilter: {
            formula: '(A / (A+B+C) * 100) - (C / (A+B+C) * 100)',
            display: ChartDisplayType.ActionsBar,
        },
    }

    const insightVizQuery: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: trendsQuery,
    }

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
                                    <LemonButton
                                        to={urls.insightNew({ query: insightVizQuery })}
                                        icon={<IconOpenInNew />}
                                        size="small"
                                        type="secondary"
                                    >
                                        Open as new insight
                                    </LemonButton>
                                </div>
                                <Query query={insightVizQuery} readOnly />
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
    const { dateRange, interval, compareFilter, defaultInterval, survey, archivedResponsesPropertyFilter } =
        useValues(surveyLogic)
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

    const trendsQuery: TrendsQuery = {
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
            ...archivedResponsesPropertyFilter,
        ],
        trendsFilter: {
            formula: formula,
            display: ChartDisplayType.ActionsBar,
        },
    }

    const insightVizQuery: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: trendsQuery,
    }

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
                                    <LemonButton
                                        to={urls.insightNew({ query: insightVizQuery })}
                                        icon={<IconOpenInNew />}
                                        size="small"
                                        type="secondary"
                                    >
                                        Open as new insight
                                    </LemonButton>
                                </div>
                                <Query query={insightVizQuery} readOnly />
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

    const { answerFilters } = useValues(surveyLogic)
    const { setAnswerFilters } = useActions(surveyLogic)
    const { data } = processedData
    const npsBreakdown = calculateNpsBreakdownFromProcessedData(processedData)
    const thumbsBreakdown = isThumbQuestion(question) ? calculateThumbsBreakdown(processedData) : null
    const chartLabels = CHART_LABELS?.[question.scale] || ['1', '2', '3']
    const isNpsRatingQuestion = question.scale === 10 && question.isNpsQuestion !== false
    const emptyRatingLabels = chartLabels.filter((_label, index) => (data[index]?.value ?? 0) === 0)
    const totalResponses = data.reduce((sum, entry) => sum + entry.value, 0)

    const tooltipContextByIndex = useMemo(
        () =>
            data.map((entry) => ({
                respondentPercentage: totalResponses > 0 ? ((entry.value / totalResponses) * 100).toFixed(1) : '0.0',
            })),
        [data, totalResponses]
    )

    const tooltipCountLabel = (value: number): JSX.Element => {
        return <span className="font-semibold tabular-nums">{value}</span>
    }

    const responseFilterKey = question.id ? getSurveyIdBasedResponseKey(question.id) : null
    const [armedRatingLabel, setArmedRatingLabel] = useState<string | null>(null)

    useEffect(() => {
        if (!armedRatingLabel) {
            return
        }

        const timeout = setTimeout(() => setArmedRatingLabel(null), 2500)
        return () => clearTimeout(timeout)
    }, [armedRatingLabel])

    const currentQuestionFilter = useMemo(
        () =>
            responseFilterKey
                ? (answerFilters.find(
                      (filter) => filter.key === responseFilterKey && filter.type === PropertyFilterType.Event
                  ) as EventPropertyFilter | undefined)
                : undefined,
        [answerFilters, responseFilterKey]
    )

    const activeRatingLabel = useMemo((): string | null => {
        if (!currentQuestionFilter || currentQuestionFilter.operator !== PropertyOperator.Exact) {
            return null
        }

        if (Array.isArray(currentQuestionFilter.value)) {
            return currentQuestionFilter.value.length === 1 ? String(currentQuestionFilter.value[0]) : null
        }

        return typeof currentQuestionFilter.value === 'string' && currentQuestionFilter.value
            ? currentQuestionFilter.value
            : null
    }, [currentQuestionFilter])

    const highlightedRatingLabel = activeRatingLabel || armedRatingLabel

    const ratingBarColors = useMemo((): string[] => {
        return chartLabels.map((label) => {
            const baseColor = isNpsRatingQuestion
                ? NPS_BUCKET_COLORS[getNpsBucketByRatingLabel(label).bucket]
                : barColor

            if (!highlightedRatingLabel || label === highlightedRatingLabel) {
                return baseColor
            }

            return hexToRGBA(baseColor, activeRatingLabel ? 0.22 : 0.35)
        })
    }, [activeRatingLabel, barColor, chartLabels, highlightedRatingLabel, isNpsRatingQuestion])

    const upsertRatingAnswerFilter = (ratingLabel: string | null): void => {
        if (!responseFilterKey) {
            return
        }

        const updatedFilters = [...answerFilters]
        const existingIndex = updatedFilters.findIndex((f) => f.key === responseFilterKey)

        if (existingIndex >= 0) {
            updatedFilters[existingIndex] = {
                ...updatedFilters[existingIndex],
                key: responseFilterKey,
                type: PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
                value: ratingLabel ? [ratingLabel] : [],
            }
        } else if (ratingLabel) {
            updatedFilters.push({
                key: responseFilterKey,
                type: PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
                value: [ratingLabel],
            })
        }

        setAnswerFilters(updatedFilters)
    }

    const handleRatingBarClick = ({ index }: GraphPointPayload): void => {
        if (!responseFilterKey) {
            return
        }

        const clickedRatingLabel = chartLabels[index]
        if (!clickedRatingLabel) {
            return
        }

        if (activeRatingLabel === clickedRatingLabel) {
            upsertRatingAnswerFilter(null)
            setArmedRatingLabel(null)
            return
        }

        if (armedRatingLabel === clickedRatingLabel) {
            upsertRatingAnswerFilter(clickedRatingLabel)
            setArmedRatingLabel(null)
            return
        }

        setArmedRatingLabel(clickedRatingLabel)
    }

    if (isThumbQuestion(question)) {
        return thumbsBreakdown ? <ThumbsBreakdownViz thumbsBreakdown={thumbsBreakdown} /> : null
    }

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
                                onClick={handleRatingBarClick}
                                tooltip={{
                                    showHeader: false,
                                    hideColorCol: true,
                                    groupTypeLabel: 'responses (double-click to filter)',
                                    renderSeries: (_value, datum) => {
                                        const ratingLabel = chartLabels[datum.dataIndex] ?? String(datum.dataIndex + 1)
                                        const context = tooltipContextByIndex[datum.dataIndex]
                                        const npsBucket = isNpsRatingQuestion
                                            ? getNpsBucketByRatingLabel(ratingLabel)
                                            : null

                                        return (
                                            <div className="space-y-0.5">
                                                <div className="flex items-center gap-2 leading-tight">
                                                    <span className="font-semibold">Rating {ratingLabel}</span>
                                                    {npsBucket && (
                                                        <span
                                                            className={`text-xs ${NPS_BUCKET_TEXT_CLASS[npsBucket.bucket]}`}
                                                        >
                                                            {npsBucket.label}
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="text-xs text-secondary leading-tight">
                                                    <span className="font-semibold text-primary">
                                                        {context?.respondentPercentage ?? '0.0'}%
                                                    </span>{' '}
                                                    respondents
                                                </div>
                                            </div>
                                        )
                                    },
                                    renderCount: tooltipCountLabel,
                                }}
                                datasets={[
                                    {
                                        id: 1,
                                        label: 'Number of responses',
                                        barPercentage: 0.8,
                                        data: data.map((d) => d.value),
                                        labels: chartLabels,
                                        backgroundColor: ratingBarColors,
                                        borderColor: ratingBarColors,
                                        hoverBackgroundColor: ratingBarColors,
                                        totalResponses,
                                    },
                                ]}
                                labels={chartLabels}
                            />
                        </BindLogic>
                    </div>
                </div>
                <div className="flex flex-row justify-between">
                    <div className="text-secondary pl-10">{question.lowerBoundLabel}</div>
                    <div className="text-secondary pr-10">{question.upperBoundLabel}</div>
                </div>
                {responseFilterKey && (
                    <div className="text-xs text-muted text-center">
                        {activeRatingLabel
                            ? `Showing only responses with rating ${activeRatingLabel}. Click the same bar to clear.`
                            : armedRatingLabel
                              ? `Click rating ${armedRatingLabel} again to show only responses with this score.`
                              : 'Double-click a rating to show only responses with that score.'}
                    </div>
                )}
                {isNpsRatingQuestion && emptyRatingLabels.length > 0 && (
                    <div className="text-xs text-muted text-center">
                        No responses at ratings: {emptyRatingLabels.join(', ')}
                    </div>
                )}
            </div>
            {question.isNpsQuestion !== false && (
                <>
                    {npsBreakdown && <NPSBreakdownViz npsBreakdown={npsBreakdown} />}
                    {question.scale === 10 && (
                        <NPSRatingOverTime questionIndex={questionIndex} questionId={question.id ?? ''} />
                    )}
                </>
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
