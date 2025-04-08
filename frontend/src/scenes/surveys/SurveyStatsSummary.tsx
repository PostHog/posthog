import { LemonLabel, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanFriendlyNumber, percentage, pluralize } from 'lib/utils'
import { memo } from 'react'
import { StackedBar, StackedBarSegment } from 'scenes/surveys/components/StackedBar'

import { SurveyStats } from '~/types'

import { surveyLogic } from './surveyLogic'

interface StatCardProps {
    title: string
    value: string | number
    description?: string | React.ReactNode
    isLoading?: boolean
}

function StatCard({ title, value, description, isLoading }: StatCardProps): JSX.Element {
    return (
        <div className="p-4 border rounded bg-bg-light flex-1 min-w-[180px]">
            <div className="text-xs font-semibold uppercase text-text-secondary mb-1">{title}</div>
            {isLoading ? (
                <LemonSkeleton className="h-8 w-16 my-1" />
            ) : (
                <div className="text-3xl font-bold">{value}</div>
            )}
            {description && <div className="text-sm text-text-secondary mt-1">{description}</div>}
        </div>
    )
}

function UsersCount({ surveyStats, isLoading }: { surveyStats: SurveyStats; isLoading: boolean }): JSX.Element {
    const { stats, rates } = surveyStats
    const uniqueUsersShown = stats['survey shown'].unique_persons
    const uniqueUsersSent = stats['survey sent'].unique_persons

    return (
        <div className="flex flex-wrap gap-4 mb-4">
            <StatCard
                title="Total Impressions by Unique Users"
                value={humanFriendlyNumber(uniqueUsersShown)}
                description={`Unique ${pluralize(uniqueUsersShown, 'user', 'users', false)}`}
                isLoading={isLoading}
            />
            <StatCard
                title="Responses"
                value={humanFriendlyNumber(uniqueUsersSent)}
                description={`Sent by unique ${pluralize(uniqueUsersSent, 'user', 'users', false)}`}
                isLoading={isLoading}
            />
            <StatCard
                title="Conversion rate by unique users"
                value={`${humanFriendlyNumber(rates.unique_users_response_rate)}%`}
                description={`${humanFriendlyNumber(uniqueUsersSent)} submitted / ${humanFriendlyNumber(
                    uniqueUsersShown
                )} shown`}
                isLoading={isLoading}
            />
        </div>
    )
}

function ResponsesCount({ surveyStats, isLoading }: { surveyStats: SurveyStats; isLoading: boolean }): JSX.Element {
    const { stats, rates } = surveyStats
    const impressions = stats['survey shown'].total_count
    const sent = stats['survey sent'].total_count

    return (
        <div className="flex flex-wrap gap-4 mb-4">
            <StatCard
                title="Total Impressions"
                value={humanFriendlyNumber(impressions)}
                isLoading={isLoading}
                description="How many times the survey was shown"
            />
            <StatCard
                title="Responses"
                value={humanFriendlyNumber(sent)}
                description="Sent by all users"
                isLoading={isLoading}
            />
            <StatCard
                title="Conversion rate by impressions"
                value={`${humanFriendlyNumber(rates.response_rate)}%`}
                description={`${humanFriendlyNumber(sent)} submitted / ${humanFriendlyNumber(impressions)} shown`}
                isLoading={isLoading}
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
    surveyStats,
    filterByDistinctId,
    isLoading,
}: {
    surveyStats: SurveyStats
    filterByDistinctId: boolean
    isLoading: boolean
}): JSX.Element {
    if (isLoading) {
        return <LemonSkeleton className="h-8 w-full" />
    }

    const { stats } = surveyStats

    const total = !filterByDistinctId ? stats['survey shown'].total_count : stats['survey shown'].unique_persons
    const onlySeen = !filterByDistinctId
        ? stats['survey shown'].total_count_only_seen
        : stats['survey shown'].unique_persons_only_seen
    const dismissed = !filterByDistinctId
        ? stats['survey dismissed'].total_count
        : stats['survey dismissed'].unique_persons
    const sent = !filterByDistinctId ? stats['survey sent'].total_count : stats['survey sent'].unique_persons

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
    const { filterSurveyStatsByDistinctId } = useValues(surveyLogic)
    const { setFilterSurveyStatsByDistinctId } = useActions(surveyLogic)

    return (
        <div>
            <div className="flex items-center gap-2 justify-between">
                <h3>Survey performance</h3>
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
            </div>
            {children}
        </div>
    )
}
function _SurveyStatsSummary(): JSX.Element {
    const { surveyUserStats, surveyUserStatsLoading, filterSurveyStatsByDistinctId } = useValues(surveyLogic)

    if (!surveyUserStats) {
        return (
            <SurveyStatsContainer>
                <div className="text-center text-text-secondary">No data available for this survey yet.</div>
            </SurveyStatsContainer>
        )
    }

    return (
        <SurveyStatsContainer>
            {filterSurveyStatsByDistinctId ? (
                <UsersCount surveyStats={surveyUserStats} isLoading={surveyUserStatsLoading} />
            ) : (
                <ResponsesCount surveyStats={surveyUserStats} isLoading={surveyUserStatsLoading} />
            )}
            <SurveyStatsStackedBar
                surveyStats={surveyUserStats}
                filterByDistinctId={filterSurveyStatsByDistinctId}
                isLoading={surveyUserStatsLoading}
            />
        </SurveyStatsContainer>
    )
}

export const SurveyStatsSummary = memo(_SurveyStatsSummary)
