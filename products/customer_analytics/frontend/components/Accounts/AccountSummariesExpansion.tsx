import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonDropdown, LemonSkeleton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'

import {
    AccountChannelSummaryApi,
    SlackSummaryCadenceEnumApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountSummariesLogic, NOT_LOADED, SUMMARIES_PAGE_SIZE } from './accountSummariesLogic'
import { AccountSummaryCadencePicker } from './AccountSummaryCadencePicker'

function SummariesEmptyState({
    title,
    detail,
    children,
}: {
    title: string
    detail: string
    children?: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <BigLeaguesHog className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
            {children}
        </div>
    )
}

function backfillDescription(cadence: SlackSummaryCadenceEnumApi | null): string {
    if (cadence === SlackSummaryCadenceEnumApi.Daily) {
        return 'Summarizing the last 7 days, one summary per day.'
    }
    return cadence === SlackSummaryCadenceEnumApi.Monthly ? 'Summarizing last month.' : 'Summarizing last week.'
}

export function periodLabel(summary: AccountChannelSummaryApi): string {
    const start = summary.period_start.slice(0, 10)
    // Span, not cadence: an opt-in backfill writes a trailing window under whichever cadence was picked.
    if (dayjs(summary.period_end).diff(summary.period_start, 'day') <= 1) {
        // period_end is exclusive, so a single day's end already reads as the next date.
        return start
    }
    return `${start} to ${summary.period_end.slice(0, 10)}`
}

function MessageCountBadge({ summary }: { summary: AccountChannelSummaryApi }): JSX.Element {
    const label = `${summary.message_count} message${summary.message_count === 1 ? '' : 's'}`
    if (!summary.messages?.length) {
        return <span>{label}</span>
    }
    return (
        // The wrapper span keeps clicks on the badge from toggling the card.
        <span onClick={(e) => e.stopPropagation()}>
            <LemonDropdown
                closeOnClickInside={false}
                overlay={
                    <div className="flex flex-col max-h-80 overflow-y-auto py-1">
                        {summary.messages.map((message, index) => (
                            <Link
                                key={index}
                                to={message.permalink}
                                target="_blank"
                                className="px-2 py-1 whitespace-nowrap"
                            >
                                {message.author} · <TZLabel time={message.sent_at} />
                            </Link>
                        ))}
                    </div>
                }
            >
                <span
                    role="button"
                    className="underline decoration-dotted cursor-pointer"
                    data-attr="account-summary-message-count"
                >
                    {label}
                </span>
            </LemonDropdown>
        </span>
    )
}

function SummaryCard({
    summary,
    expanded,
    onToggle,
}: {
    summary: AccountChannelSummaryApi
    expanded: boolean
    onToggle: () => void
}): JSX.Element {
    return (
        <div className="border rounded bg-surface-primary">
            <div
                role="button"
                aria-expanded={expanded}
                className={clsx(
                    'flex items-center gap-2 p-4 cursor-pointer hover:bg-surface-secondary',
                    expanded ? 'rounded-t' : 'rounded'
                )}
                onClick={onToggle}
            >
                <LemonTag type="default">{summary.cadence}</LemonTag>
                <span className="font-semibold">{periodLabel(summary)}</span>
                <span className="text-muted text-xs ml-auto flex items-center gap-1">
                    <MessageCountBadge summary={summary} /> · generated <TZLabel time={summary.generated_at} />
                </span>
            </div>
            {expanded && (
                <LemonMarkdown lowKeyHeadings disableImages disableDocsRedirect className="text-sm px-4 pt-3 pb-4">
                    {summary.content}
                </LemonMarkdown>
            )}
        </div>
    )
}

export function AccountSummariesExpansion({ accountId }: { accountId: string }): JSX.Element {
    const { summariesResult, summariesResultLoading, page, expandedSummaryIds, generatingFirstSummary } = useValues(
        accountSummariesLogic({ accountId })
    )
    const { loadSummariesPage, toggleSummaryExpanded } = useActions(accountSummariesLogic({ accountId }))

    if ((summariesResultLoading && summariesResult === NOT_LOADED) || summariesResult === NOT_LOADED) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    const { summaries, totalCount, slackChannelId, cadence, loadFailed } = summariesResult

    if (loadFailed) {
        return (
            <SummariesEmptyState
                title="Couldn't load summaries"
                detail="Something went wrong loading this account's channel summaries. Try refreshing the page."
            />
        )
    }

    if (!slackChannelId) {
        return (
            <SummariesEmptyState
                title="No Slack channel linked"
                detail="Link a Slack channel to this account in its properties first. Once a channel is linked, you can turn on periodic AI summaries of it here."
            />
        )
    }

    if (!summaries || summaries.length === 0) {
        if (generatingFirstSummary) {
            return (
                <SummariesEmptyState
                    title={
                        cadence === SlackSummaryCadenceEnumApi.Daily
                            ? 'Generating your first summaries'
                            : 'Generating your first summary'
                    }
                    detail={`${backfillDescription(cadence)} This usually takes a minute.`}
                >
                    <Spinner className="text-xl" />
                    <AccountSummaryCadencePicker accountId={accountId} />
                </SummariesEmptyState>
            )
        }
        return (
            <SummariesEmptyState
                title={cadence ? 'No summaries yet' : 'Summaries are off'}
                detail={
                    cadence
                        ? 'The first summary will appear once the current period closes and gets summarized.'
                        : "Get periodic AI summaries of this account's Slack channel, citing the original messages. Pick a cadence to turn them on."
                }
            >
                <AccountSummaryCadencePicker accountId={accountId} />
            </SummariesEmptyState>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <h4 className="mb-0">Channel summaries</h4>
                    {generatingFirstSummary && (
                        <span className="text-muted text-sm flex items-center gap-1">
                            <Spinner /> Generating more
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-muted text-sm">Cadence</span>
                    <AccountSummaryCadencePicker accountId={accountId} />
                </div>
            </div>
            {summaries.map((summary) => (
                <SummaryCard
                    key={summary.id}
                    summary={summary}
                    expanded={!!expandedSummaryIds[summary.id]}
                    onToggle={() => toggleSummaryExpanded(summary.id)}
                />
            ))}
            <PaginationControl
                pagination={{ controlled: true, pageSize: SUMMARIES_PAGE_SIZE }}
                currentPage={page}
                setCurrentPage={(newPage) => !summariesResultLoading && loadSummariesPage({ page: newPage })}
                pageCount={Math.max(1, Math.ceil(totalCount / SUMMARIES_PAGE_SIZE))}
                dataSourcePage={summaries}
                entryCount={totalCount}
                currentStartIndex={(page - 1) * SUMMARIES_PAGE_SIZE}
                currentEndIndex={(page - 1) * SUMMARIES_PAGE_SIZE + summaries.length}
                nouns={['summary', 'summaries']}
            />
        </div>
    )
}
