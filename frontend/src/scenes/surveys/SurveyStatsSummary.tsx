import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber, percentage, pluralize } from 'lib/utils'
import { CopySurveyLink } from 'scenes/surveys/CopySurveyLink'
import { StackedBar, StackedBarSegment, StackedBarSkeleton } from 'scenes/surveys/components/StackedBar'

import { SurveyEventName, SurveyRates, SurveyStats, SurveyType } from '~/types'

import { surveyLogic } from './surveyLogic'

interface StatRowItem {
    title: string
    value: string | number
    description: string | React.ReactNode
    valueClassName?: string
}

function StatRow({ items, isLoading }: { items: StatRowItem[]; isLoading?: boolean }): JSX.Element {
    return (
        <div className="flex flex-wrap sm:flex-nowrap items-stretch border rounded bg-bg-light/40">
            {items.map((item, index) => (
                <div
                    key={item.title}
                    className={`flex-1 min-w-[160px] px-3 py-2 flex flex-col items-center text-center ${
                        index > 0 ? 'sm:border-l border-border' : ''
                    }`}
                >
                    <div className="text-xs font-semibold uppercase text-text-secondary">{item.title}</div>
                    {isLoading ? (
                        <>
                            <LemonSkeleton className="h-6 w-16 mt-1" />
                            <LemonSkeleton className="h-3 w-24 mt-1" />
                        </>
                    ) : (
                        <>
                            <div className={`text-2xl font-semibold leading-tight ${item.valueClassName ?? ''}`}>
                                {item.value}
                            </div>
                            <div className="text-xs text-text-secondary">{item.description}</div>
                        </>
                    )}
                </div>
            ))}
        </div>
    )
}

function UsersCount({ stats, rates }: { stats: SurveyStats; rates: SurveyRates }): JSX.Element {
    const uniqueUsersShown = stats[SurveyEventName.SHOWN].unique_persons
    const uniqueUsersSent = stats[SurveyEventName.SENT].unique_persons
    const { answerFilterHogQLExpression } = useValues(surveyLogic)
    const filterNote = answerFilterHogQLExpression ? ' · filtered' : ''
    return (
        <StatRow
            items={[
                {
                    title: 'Shown',
                    value: humanFriendlyNumber(uniqueUsersShown),
                    description: `Unique ${pluralize(uniqueUsersShown, 'user', 'users', false)}`,
                    valueClassName: 'text-text-primary',
                },
                {
                    title: 'Responses',
                    value: humanFriendlyNumber(uniqueUsersSent),
                    description: `Unique users${filterNote}`,
                    valueClassName: 'text-success',
                },
                {
                    title: 'Conversion',
                    value: `${humanFriendlyNumber(rates.unique_users_response_rate)}%`,
                    description: `${humanFriendlyNumber(uniqueUsersSent)} / ${humanFriendlyNumber(uniqueUsersShown)}`,
                    valueClassName: 'text-primary',
                },
            ]}
        />
    )
}

function ResponsesCount({ stats, rates }: { stats: SurveyStats; rates: SurveyRates }): JSX.Element {
    const impressions = stats[SurveyEventName.SHOWN].total_count
    const sent = stats[SurveyEventName.SENT].total_count
    const { answerFilterHogQLExpression } = useValues(surveyLogic)
    const filterNote = answerFilterHogQLExpression ? ' · filtered' : ''

    return (
        <StatRow
            items={[
                {
                    title: 'Shown',
                    value: humanFriendlyNumber(impressions),
                    description: 'Impressions',
                    valueClassName: 'text-text-primary',
                },
                {
                    title: 'Responses',
                    value: humanFriendlyNumber(sent),
                    description: `Responses${filterNote}`,
                    valueClassName: 'text-success',
                },
                {
                    title: 'Conversion',
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

    return <StackedBar segments={segments} size="sm" />
}

function SurveyStatsContainer({ children }: { children: React.ReactNode }): JSX.Element {
    const { filterSurveyStatsByDistinctId, processedSurveyStats, survey } = useValues(surveyLogic)
    const { setFilterSurveyStatsByDistinctId } = useActions(surveyLogic)

    const isPubliclyShareable = survey.type === SurveyType.ExternalSurvey

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 justify-between">
                <h3 className="mb-0">Survey performance</h3>
                <div className="flex items-center gap-2">
                    {isPubliclyShareable && (
                        <CopySurveyLink
                            surveyId={survey.id}
                            enableIframeEmbedding={survey.enable_iframe_embedding ?? false}
                        />
                    )}
                    {processedSurveyStats && processedSurveyStats[SurveyEventName.SHOWN].total_count > 0 && (
                        <LemonSwitch
                            checked={filterSurveyStatsByDistinctId}
                            onChange={(checked) => setFilterSurveyStatsByDistinctId(checked)}
                            tooltip="If enabled, each user will only be counted once, even if they have multiple responses."
                            label="Count each person once"
                        />
                    )}
                </div>
            </div>
            {survey.start_date && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                    <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${
                            survey.end_date ? 'bg-danger/10 text-danger' : 'bg-success/10 text-success'
                        }`}
                    >
                        <span
                            className={`h-1.5 w-1.5 rounded-full ${
                                survey.end_date ? 'bg-danger' : 'bg-success animate-pulse'
                            }`}
                        />
                        {survey.end_date ? 'Ended' : 'Active'}
                    </span>
                    <span className="text-border-dark">•</span>
                    <Tooltip title={<TZLabel time={survey.start_date} />}>
                        <span>Started {dayjs(survey.start_date).fromNow()}</span>
                    </Tooltip>
                    {survey.end_date && (
                        <>
                            <span className="text-border-dark">•</span>
                            <Tooltip title={<TZLabel time={survey.end_date} />}>
                                <span>Ended {dayjs(survey.end_date).fromNow()}</span>
                            </Tooltip>
                        </>
                    )}
                </div>
            )}
            <div className="flex flex-col gap-3">{children}</div>
        </div>
    )
}

function DemoStatsContainer({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 justify-between">
                <h3 className="mb-0">Survey performance</h3>
            </div>
            <div className="flex flex-col gap-3">{children}</div>
        </div>
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
                        title: 'Conversion',
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
}: {
    processedSurveyStats: SurveyStats
    surveyRates: SurveyRates
    isLoading?: boolean
}): JSX.Element {
    if (isLoading) {
        return <SurveyStatsSummarySkeleton />
    }

    return (
        <DemoStatsContainer>
            <UsersCount stats={processedSurveyStats} rates={surveyRates} />
            <SurveyStatsStackedBar stats={processedSurveyStats} filterByDistinctId={true} />
        </DemoStatsContainer>
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
            {surveyRates && (
                <>
                    {filterSurveyStatsByDistinctId ? (
                        <UsersCount stats={processedSurveyStats} rates={surveyRates} />
                    ) : (
                        <ResponsesCount stats={processedSurveyStats} rates={surveyRates} />
                    )}
                </>
            )}
            <SurveyStatsStackedBar stats={processedSurveyStats} filterByDistinctId={filterSurveyStatsByDistinctId} />
        </SurveyStatsContainer>
    )
})
