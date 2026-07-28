import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonButton, LemonSelect, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import {
    AccountChannelSummaryApi,
    SlackSummaryCadenceEnumApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountSummariesLogic, NOT_LOADED } from './accountSummariesLogic'

const CADENCE_OPTIONS: { value: SlackSummaryCadenceEnumApi | null; label: string }[] = [
    { value: null, label: 'Off' },
    { value: SlackSummaryCadenceEnumApi.Daily, label: 'Daily' },
    { value: SlackSummaryCadenceEnumApi.Weekly, label: 'Weekly' },
    { value: SlackSummaryCadenceEnumApi.Monthly, label: 'Monthly' },
]

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

function CadencePicker({ accountId }: { accountId: string }): JSX.Element {
    const { summariesResult, cadenceSaving } = useValues(accountSummariesLogic({ accountId }))
    const { setCadence } = useActions(accountSummariesLogic({ accountId }))
    return (
        <LemonSelect<SlackSummaryCadenceEnumApi | null>
            size="small"
            value={summariesResult.cadence}
            options={CADENCE_OPTIONS}
            onChange={(value) => setCadence(value)}
            disabledReason={cadenceSaving ? 'Saving…' : undefined}
            data-attr="account-summary-cadence-picker"
        />
    )
}

function periodLabel(summary: AccountChannelSummaryApi): string {
    const start = summary.period_start.slice(0, 10)
    // period_end is exclusive; a daily summary covers a single day.
    return summary.cadence === 'daily' ? start : `${start} to ${summary.period_end.slice(0, 10)}`
}

function SummaryCard({ summary }: { summary: AccountChannelSummaryApi }): JSX.Element {
    return (
        <div className="border rounded p-4 bg-surface-primary flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <LemonTag type="default">{summary.cadence}</LemonTag>
                <span className="font-semibold">{periodLabel(summary)}</span>
                <span className="text-muted text-xs ml-auto flex items-center gap-1">
                    {summary.message_count} message{summary.message_count === 1 ? '' : 's'} · generated{' '}
                    <TZLabel time={summary.generated_at} />
                </span>
            </div>
            <LemonMarkdown lowKeyHeadings disableImages disableDocsRedirect className="text-sm">
                {summary.content}
            </LemonMarkdown>
        </div>
    )
}

export function AccountSummariesExpansion({ accountId }: { accountId: string }): JSX.Element {
    const { summariesResult, summariesResultLoading } = useValues(accountSummariesLogic({ accountId }))
    const { loadMoreSummaries } = useActions(accountSummariesLogic({ accountId }))

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
        return (
            <SummariesEmptyState
                title={cadence ? 'No summaries yet' : 'Summaries are off'}
                detail={
                    cadence
                        ? 'The first summary will appear once the current period closes and gets summarized.'
                        : "Get periodic AI summaries of this account's Slack channel, citing the original messages. Pick a cadence to turn them on."
                }
            >
                <CadencePicker accountId={accountId} />
            </SummariesEmptyState>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
                <h4 className="mb-0">Channel summaries</h4>
                <div className="flex items-center gap-2">
                    <span className="text-muted text-sm">Cadence</span>
                    <CadencePicker accountId={accountId} />
                </div>
            </div>
            {summaries.map((summary) => (
                <SummaryCard key={summary.id} summary={summary} />
            ))}
            {summaries.length < totalCount && (
                <LemonButton
                    type="secondary"
                    center
                    loading={summariesResultLoading}
                    onClick={() => loadMoreSummaries()}
                >
                    Load more
                </LemonButton>
            )}
        </div>
    )
}
