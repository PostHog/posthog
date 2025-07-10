import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { LemonLabel, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber, percentage, pluralize } from 'lib/utils'
import { StackedBar, StackedBarSegment, StackedBarSkeleton } from 'scenes/surveys/components/StackedBar'

import { SurveyEventName, SurveyRates, SurveyStats } from '~/types'

import { surveyLogic } from './surveyLogic'

interface StatCardProps {
    title: string
    value: string | number
    description: string | React.ReactNode
    isLoading?: boolean
}

function StatCard({ title, value, description, isLoading }: StatCardProps): JSX.Element {
    return (
        <div className="bg-bg-light flex min-w-[180px] flex-1 flex-col gap-1 rounded border p-4">
            <div className="text-text-secondary text-xs font-semibold uppercase">{title}</div>
            {isLoading ? (
                <>
                    <LemonSkeleton className="h-9 w-16" />
                    <LemonSkeleton className="h-4 w-32" />
                </>
            ) : (
                <>
                    <div className="text-3xl font-bold">{value}</div>
                    <div className="text-text-secondary text-sm">{description}</div>
                </>
            )}
        </div>
    )
}

function UsersCount({ stats, rates }: { stats: SurveyStats; rates: SurveyRates }): JSX.Element {
    const uniqueUsersShown = stats[SurveyEventName.SHOWN].unique_persons
    const uniqueUsersSent = stats[SurveyEventName.SENT].unique_persons
    const { answerFilterHogQLExpression } = useValues(surveyLogic)
    return (
        <div className="flex flex-wrap gap-4">
            <StatCard
                title="Total Impressions by Unique Users"
                value={humanFriendlyNumber(uniqueUsersShown)}
                description={`Unique ${pluralize(uniqueUsersShown, 'user', 'users', false)}`}
            />
            <StatCard
                title="Responses"
                value={humanFriendlyNumber(uniqueUsersSent)}
                description={`Sent by unique ${pluralize(uniqueUsersSent, 'user', 'users', false)}${
                    answerFilterHogQLExpression ? ` with the applied answer filters` : ''
                }`}
            />
            <StatCard
                title="Conversion rate by unique users"
                value={`${humanFriendlyNumber(rates.unique_users_response_rate)}%`}
                description={`${humanFriendlyNumber(uniqueUsersSent)} submitted / ${humanFriendlyNumber(
                    uniqueUsersShown
                )} shown`}
            />
        </div>
    )
}

function ResponsesCount({ stats, rates }: { stats: SurveyStats; rates: SurveyRates }): JSX.Element {
    const impressions = stats[SurveyEventName.SHOWN].total_count
    const sent = stats[SurveyEventName.SENT].total_count
    const { answerFilterHogQLExpression } = useValues(surveyLogic)

    return (
        <div className="flex flex-wrap gap-4">
            <StatCard
                title="Total Impressions"
                value={humanFriendlyNumber(impressions)}
                description="How many times the survey was shown"
            />
            <StatCard
                title="Responses"
                value={humanFriendlyNumber(sent)}
                description={`Sent by all users${
                    answerFilterHogQLExpression ? ` with the applied answer filters` : ''
                }`}
            />
            <StatCard
                title="Conversion rate by impressions"
                value={`${humanFriendlyNumber(rates.response_rate)}%`}
                description={`${humanFriendlyNumber(sent)} submitted / ${humanFriendlyNumber(impressions)} shown`}
            />
        </div>
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
            label: 'Submitted',
            colorClass: 'bg-success',
            tooltip: getTooltip(sent, total, filterByDistinctId),
        },
        {
            count: dismissed,
            label: 'Dismissed',
            colorClass: 'bg-warning',
            tooltip: getTooltip(dismissed, total, filterByDistinctId),
        },
        {
            count: onlySeen,
            label: 'Unanswered',
            colorClass: 'bg-brand-blue',
            tooltip: getTooltip(onlySeen, total, filterByDistinctId),
        },
    ]

    return <StackedBar segments={segments} />
}

function SurveyStatsContainer({ children }: { children: React.ReactNode }): JSX.Element {
    const { filterSurveyStatsByDistinctId, processedSurveyStats, survey } = useValues(surveyLogic)
    const { setFilterSurveyStatsByDistinctId } = useActions(surveyLogic)

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2">
                <h3 className="mb-0">Survey performance</h3>
                {processedSurveyStats && processedSurveyStats[SurveyEventName.SHOWN].total_count > 0 && (
                    <div className="flex items-center gap-2">
                        <LemonLabel>
                            Count each person once
                            <LemonSwitch
                                checked={filterSurveyStatsByDistinctId}
                                onChange={(checked) => setFilterSurveyStatsByDistinctId(checked)}
                                tooltip="If enabled, each user will only be counted once, even if they have multiple responses."
                            />
                        </LemonLabel>
                    </div>
                )}
            </div>
            {survey.start_date && (
                <div className="text-secondary flex items-center text-sm">
                    <div className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-1">
                            Started: <TZLabel time={survey.start_date} />
                        </span>
                        <span className="text-border-dark">•</span>
                        {survey.end_date ? (
                            <span className="inline-flex items-center gap-1">
                                <span className="bg-danger/50 h-2 w-2 rounded-full" />
                                Ended: <TZLabel time={survey.end_date} />
                            </span>
                        ) : (
                            <span className="text-success inline-flex items-center gap-1">
                                <span className="bg-success h-2 w-2 animate-pulse rounded-full" />
                                Active
                            </span>
                        )}
                    </div>
                </div>
            )}
            <div className="flex flex-col gap-4">{children}</div>
        </div>
    )
}

function SurveyStatsSummarySkeleton(): JSX.Element {
    return (
        <SurveyStatsContainer>
            <div className="flex flex-wrap gap-4">
                <StatCard
                    title="Total Impressions by Unique Users"
                    value={0}
                    description={`Unique ${pluralize(0, 'user', 'users', false)}`}
                    isLoading={true}
                />
                <StatCard
                    title="Responses"
                    value={0}
                    description={`Sent by unique ${pluralize(0, 'user', 'users', false)}`}
                    isLoading={true}
                />
                <StatCard
                    title="Conversion rate by unique users"
                    value="0%"
                    description="0 submitted / 0 shown"
                    isLoading={true}
                />
            </div>
            <StackedBarSkeleton />
        </SurveyStatsContainer>
    )
}

export const SurveyStatsSummary = memo(function SurveyStatsSummary(): JSX.Element {
    const {
        filterSurveyStatsByDistinctId,
        processedSurveyStats,
        surveyRates,
        surveyBaseStatsLoading,
        surveyDismissedAndSentCountLoading,
    } = useValues(surveyLogic)

    if (surveyBaseStatsLoading || surveyDismissedAndSentCountLoading) {
        return <SurveyStatsSummarySkeleton />
    }

    if (!processedSurveyStats) {
        return (
            <SurveyStatsContainer>
                <div className="text-text-secondary text-left">No data available for this survey yet.</div>
            </SurveyStatsContainer>
        )
    }

    return (
        <SurveyStatsContainer>
            {filterSurveyStatsByDistinctId ? (
                <UsersCount stats={processedSurveyStats} rates={surveyRates} />
            ) : (
                <ResponsesCount stats={processedSurveyStats} rates={surveyRates} />
            )}
            <SurveyStatsStackedBar stats={processedSurveyStats} filterByDistinctId={filterSurveyStatsByDistinctId} />
        </SurveyStatsContainer>
    )
})
