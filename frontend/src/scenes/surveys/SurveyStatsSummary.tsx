import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanFriendlyNumber, percentage, pluralize } from 'lib/utils'
import { memo } from 'react'
import { StackedBar, StackedBarSegment } from 'scenes/surveys/components/StackedBar'

import { surveyLogic, SurveyUserStats } from './surveyLogic'

interface StatCardProps {
    title: string
    value: string | number
    description?: string | React.ReactNode
    valueLoading?: boolean
}

function StatCard({ title, value, description, valueLoading }: StatCardProps): JSX.Element {
    return (
        <div className="p-4 border rounded bg-bg-light flex-1 min-w-[180px]">
            <div className="text-xs font-semibold uppercase text-text-secondary mb-1">{title}</div>
            {valueLoading ? (
                <LemonSkeleton className="h-8 w-16 my-1" />
            ) : (
                <div className="text-3xl font-bold">{value}</div>
            )}
            {description && <div className="text-sm text-text-secondary mt-1">{description}</div>}
        </div>
    )
}

function UsersCount({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { uniqueUsersOnlySeen, uniqueUsersDismissed, uniqueUsersSent, totalSent } = surveyUserStats
    const uniqueUsersShown = uniqueUsersOnlySeen + uniqueUsersDismissed + uniqueUsersSent
    const conversionRate = uniqueUsersShown > 0 ? uniqueUsersSent / uniqueUsersShown : 0

    return (
        <div className="flex flex-wrap gap-4 mb-4">
            <StatCard
                title="Total Unique Users Reached"
                value={humanFriendlyNumber(uniqueUsersShown)}
                description={`Unique ${pluralize(uniqueUsersShown, 'user', 'users', false)}`}
            />
            <StatCard
                title="Responses"
                value={humanFriendlyNumber(uniqueUsersSent)}
                description={
                    <>
                        Sent by unique {pluralize(uniqueUsersSent, 'user', 'users', false)}{' '}
                        {totalSent !== uniqueUsersSent && (
                            <span className="text-text-secondary">
                                ({humanFriendlyNumber(totalSent)} total responses)
                            </span>
                        )}
                    </>
                }
            />
            <StatCard
                title="Conversion rate (by unique users)"
                value={percentage(conversionRate, 1)}
                description={`${humanFriendlyNumber(uniqueUsersSent)} submitted / ${humanFriendlyNumber(
                    uniqueUsersShown
                )} shown`}
            />
        </div>
    )
}

function UsersStackedBar({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { uniqueUsersOnlySeen, uniqueUsersDismissed, uniqueUsersSent } = surveyUserStats
    const total = uniqueUsersOnlySeen + uniqueUsersDismissed + uniqueUsersSent

    const segments: StackedBarSegment[] = [
        {
            count: uniqueUsersSent,
            label: 'Submitted',
            colorClass: 'bg-success',
            tooltip: `${humanFriendlyNumber(uniqueUsersSent)} unique ${pluralize(
                uniqueUsersSent,
                'user',
                'users',
                false
            )} submitted a response (${percentage(uniqueUsersSent / total, 1)})`,
        },
        {
            count: uniqueUsersDismissed,
            label: 'Dismissed',
            colorClass: 'bg-warning',
            tooltip: `${humanFriendlyNumber(uniqueUsersDismissed)} unique ${pluralize(
                uniqueUsersDismissed,
                'user',
                'users',
                false
            )} dismissed the survey (${percentage(uniqueUsersDismissed / total, 1)})`,
        },
        {
            count: uniqueUsersOnlySeen,
            label: 'Seen (no response)',
            colorClass: 'bg-brand-blue',
            tooltip: `${humanFriendlyNumber(uniqueUsersOnlySeen)} unique ${pluralize(
                uniqueUsersOnlySeen,
                'user',
                'users',
                false
            )} saw the survey but didn't respond or dismiss (${percentage(uniqueUsersOnlySeen / total, 1)})`,
        },
    ]

    return <StackedBar segments={segments} />
}

function _SurveyStatsSummary(): JSX.Element {
    const { surveyUserStats, surveyUserStatsLoading } = useValues(surveyLogic)

    return (
        <div>
            <h3>Survey performance</h3>
            {surveyUserStatsLoading ? (
                <>
                    {/* Skeleton for StatCards */}
                    <div className="flex flex-wrap gap-4 mb-4">
                        <StatCard title="Total Unique Users Reached" value="" valueLoading />
                        <StatCard title="Responses" value="" valueLoading />
                        <StatCard title="Conversion rate (by unique users)" value="" valueLoading />
                    </div>
                    {/* Skeleton for StackedBar */}
                    <LemonSkeleton className="h-8 w-full" />
                </>
            ) : (
                <>
                    {!surveyUserStats ? (
                        <div className="text-center text-text-secondary">No data available for this survey yet.</div>
                    ) : (
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

export const SurveyStatsSummary = memo(_SurveyStatsSummary)
