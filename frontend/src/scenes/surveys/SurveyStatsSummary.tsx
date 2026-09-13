import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { StackedBar, StackedBarSegment, StackedBarSkeleton } from 'scenes/surveys/components/StackedBar'
import { CopySurveyLink } from 'scenes/surveys/CopySurveyLink'

import { SurveyEventName, SurveyRates, SurveyStats, SurveyType } from '~/types'

import { SurveyResponseBreakdown } from 'products/surveys/frontend/components/SurveyResponseBreakdown'

import { surveyLogic } from './surveyLogic'

interface StatRowItem {
    title: string
    value: string | number
    description: string | React.ReactNode
    valueClassName?: string
}

function StatRow({
    items,
    isLoading,
    controls,
}: {
    items: StatRowItem[]
    isLoading?: boolean
    controls?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col @min-[56rem]/survey-performance:flex-row @min-[56rem]/survey-performance:items-center gap-x-8 gap-y-3">
            <dl className="flex flex-1 flex-wrap items-baseline gap-x-8 gap-y-3 m-0">
                {items.map((item) => (
                    <div
                        key={item.title}
                        className="flex w-full @min-[40rem]/survey-performance:w-auto items-baseline justify-between gap-2"
                    >
                        <dt className="text-sm text-secondary">{item.title}</dt>
                        <dd className="m-0">
                            {isLoading ? (
                                <LemonSkeleton className="h-6 w-16" />
                            ) : (
                                <Tooltip title={item.description}>
                                    <span className={`text-xl font-semibold tabular-nums ${item.valueClassName ?? ''}`}>
                                        {item.value}
                                    </span>
                                </Tooltip>
                            )}
                        </dd>
                    </div>
                ))}
            </dl>
            {controls}
        </div>
    )
}

function UsersCount({
    stats,
    rates,
    controls,
}: {
    stats: SurveyStats
    rates: SurveyRates
    controls?: React.ReactNode
}): JSX.Element {
    const uniqueUsersShown = stats[SurveyEventName.SHOWN].unique_persons
    const uniqueUsersSent = stats[SurveyEventName.SENT].unique_persons
    const { answerFilterHogQLExpression } = useValues(surveyLogic)
    const filterNote = answerFilterHogQLExpression ? ' · filtered' : ''
    return (
        <StatRow
            controls={controls}
            items={[
                {
                    title: 'Shown',
                    value: humanFriendlyNumber(uniqueUsersShown),
                    description: `Unique ${pluralize(uniqueUsersShown, 'user', 'users', false)}`,
                    valueClassName: 'text-text-primary',
                },
                {
                    title: answerFilterHogQLExpression ? 'Responses (filtered)' : 'Responses',
                    value: humanFriendlyNumber(uniqueUsersSent),
                    description: `Unique users${filterNote}`,
                    valueClassName: 'text-text-primary',
                },
                {
                    title: 'Response rate',
                    value: `${humanFriendlyNumber(rates.unique_users_response_rate)}%`,
                    description: `${humanFriendlyNumber(uniqueUsersSent)} / ${humanFriendlyNumber(uniqueUsersShown)}`,
                    valueClassName: 'text-primary',
                },
            ]}
        />
    )
}

function ResponsesCount({
    stats,
    rates,
    controls,
}: {
    stats: SurveyStats
    rates: SurveyRates
    controls?: React.ReactNode
}): JSX.Element {
    const impressions = stats[SurveyEventName.SHOWN].total_count
    const sent = stats[SurveyEventName.SENT].total_count
    const { answerFilterHogQLExpression } = useValues(surveyLogic)
    const filterNote = answerFilterHogQLExpression ? ' · filtered' : ''

    return (
        <StatRow
            controls={controls}
            items={[
                {
                    title: 'Shown',
                    value: humanFriendlyNumber(impressions),
                    description: 'Impressions',
                    valueClassName: 'text-text-primary',
                },
                {
                    title: answerFilterHogQLExpression ? 'Responses (filtered)' : 'Responses',
                    value: humanFriendlyNumber(sent),
                    description: `Responses${filterNote}`,
                    valueClassName: 'text-text-primary',
                },
                {
                    title: 'Response rate',
                    value: `${humanFriendlyNumber(rates.response_rate)}%`,
                    description: `${humanFriendlyNumber(sent)} / ${humanFriendlyNumber(impressions)}`,
                    valueClassName: 'text-primary',
                },
            ]}
        />
    )
}

function getTooltip(count: number, total: number, isFilteredByDistinctId: boolean): string {
    const singular = isFilteredByDistinctId ? 'user' : 'response'
    const plural = isFilteredByDistinctId ? 'users' : 'responses'

    if (total <= 0) {
        return `${humanFriendlyNumber(count)} ${isFilteredByDistinctId ? 'unique' : ''} ${pluralize(
            count,
            singular,
            plural,
            false
        )}`
    }

    return `${humanFriendlyNumber(count)} ${isFilteredByDistinctId ? 'unique' : ''} ${pluralize(
        count,
        singular,
        plural,
        false
    )} (${percentage(count / total, 1)})`
}

function SurveyStatsStackedBar({
    stats,
    filterByDistinctId,
}: {
    stats: SurveyStats
    filterByDistinctId: boolean
}): JSX.Element {
    const total = !filterByDistinctId
        ? stats[SurveyEventName.SHOWN].total_count
        : stats[SurveyEventName.SHOWN].unique_persons
    const onlySeen = !filterByDistinctId
        ? stats[SurveyEventName.SHOWN].total_count_only_seen
        : stats[SurveyEventName.SHOWN].unique_persons_only_seen
    const dismissed = !filterByDistinctId
        ? stats[SurveyEventName.DISMISSED].total_count
        : stats[SurveyEventName.DISMISSED].unique_persons
    const sent = !filterByDistinctId
        ? stats[SurveyEventName.SENT].total_count
        : stats[SurveyEventName.SENT].unique_persons

    const segments: StackedBarSegment[] = [
        {
            count: sent,
            label: 'Responses',
            colorClass: 'bg-success',
            tooltip: getTooltip(sent, total, filterByDistinctId),
        },
        {
            count: dismissed,
            label: 'Dismissed without answers',
            colorClass: 'bg-warning',
            tooltip: getTooltip(dismissed, total, filterByDistinctId),
        },
        {
            count: onlySeen,
            label: 'Unanswered',
            colorClass: 'bg-muted',
            tooltip: getTooltip(onlySeen, total, filterByDistinctId),
        },
    ]

    return <StackedBar segments={segments} size="sm" />
}

function SurveyStatsContainer({ children }: { children: React.ReactNode }): JSX.Element {
    const { survey } = useValues(surveyLogic)

    const isPubliclyShareable = survey.type === SurveyType.ExternalSurvey

    return (
        <section aria-label="Survey performance" className="@container/survey-performance flex flex-col gap-4">
            {isPubliclyShareable && (
                <div className="flex justify-end">
                    <CopySurveyLink
                        surveyId={survey.id}
                        enableIframeEmbedding={survey.enable_iframe_embedding ?? false}
                    />
                </div>
            )}
            <div className="flex flex-col gap-4">{children}</div>
        </section>
    )
}

function SurveyStatsSummarySkeleton(): JSX.Element {
    return (
        <SurveyStatsContainer>
            <StatRow
                isLoading
                items={[
                    {
                        title: 'Shown',
                        value: 0,
                        description: `Unique ${pluralize(0, 'user', 'users', false)}`,
                    },
                    {
                        title: 'Responses',
                        value: 0,
                        description: `Unique ${pluralize(0, 'user', 'users', false)}`,
                    },
                    {
                        title: 'Response rate',
                        value: '0%',
                        description: '0 / 0',
                    },
                ]}
            />
            <StackedBarSkeleton size="sm" />
        </SurveyStatsContainer>
    )
}

export function SurveyStatsSummaryWithData({
    processedSurveyStats,
    surveyRates,
    isLoading = false,
    outcomes,
}: {
    processedSurveyStats: SurveyStats
    surveyRates: SurveyRates
    isLoading?: boolean
    outcomes?: React.ComponentProps<typeof SurveyResponseBreakdown>['outcomes']
}): JSX.Element {
    if (isLoading) {
        return <SurveyStatsSummarySkeleton />
    }

    return (
        <section aria-label="Survey performance" className="@container/survey-performance flex flex-col gap-4">
            <UsersCount stats={processedSurveyStats} rates={surveyRates} />
            <SurveyStatsStackedBar stats={processedSurveyStats} filterByDistinctId={true} />
            {outcomes && <SurveyResponseBreakdown outcomes={outcomes} />}
        </section>
    )
}

export const SurveyStatsSummary = memo(function SurveyStatsSummary(): JSX.Element {
    const {
        filterSurveyStatsByDistinctId,
        processedSurveyStats,
        surveyRates,
        surveyBaseStatsLoading,
        surveyDismissedAndSentCountLoading,
        resultsRequeryInProgress,
        surveyResponseOutcomes,
    } = useValues(surveyLogic)

    const { setFilterSurveyStatsByDistinctId } = useActions(surveyLogic)

    if (
        !processedSurveyStats &&
        (surveyBaseStatsLoading || surveyDismissedAndSentCountLoading || resultsRequeryInProgress)
    ) {
        return <SurveyStatsSummarySkeleton />
    }

    if (!processedSurveyStats) {
        return (
            <SurveyStatsContainer>
                <div className="text-text-secondary text-left">No data available for this survey yet.</div>
            </SurveyStatsContainer>
        )
    }

    const countToggle =
        processedSurveyStats[SurveyEventName.SHOWN].total_count > 0 ? (
            <Tooltip title="Count each person once in the performance metrics, even if they see or respond to the survey multiple times. When off, count every view and response. Response completion always counts individual submissions.">
                <div>
                    <LemonSwitch
                        data-attr="survey-stats-count-person-once"
                        checked={filterSurveyStatsByDistinctId}
                        onChange={(checked) => setFilterSurveyStatsByDistinctId(checked)}
                        label="Count each person once"
                    />
                </div>
            </Tooltip>
        ) : null

    return (
        <SurveyStatsContainer>
            {surveyRates && (
                <>
                    {filterSurveyStatsByDistinctId ? (
                        <UsersCount stats={processedSurveyStats} rates={surveyRates} controls={countToggle} />
                    ) : (
                        <ResponsesCount stats={processedSurveyStats} rates={surveyRates} controls={countToggle} />
                    )}
                </>
            )}
            <SurveyStatsStackedBar stats={processedSurveyStats} filterByDistinctId={filterSurveyStatsByDistinctId} />
            {surveyResponseOutcomes && <SurveyResponseBreakdown outcomes={surveyResponseOutcomes} />}
        </SurveyStatsContainer>
    )
})
