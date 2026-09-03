import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import {
    accountSummariesLogic,
    NOT_LOADED,
} from 'products/customer_analytics/frontend/components/Accounts/accountSummariesLogic'
import { AccountSummaryCadencePicker } from 'products/customer_analytics/frontend/components/Accounts/AccountSummaryCadencePicker'
import type { AccountChannelSummaryApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountWidgetCard } from './AccountWidgetCard'

interface AccountSummaryWidgetProps {
    accountId: string
    onRemove?: () => void
}

function SummaryMeta({ summary }: { summary: AccountChannelSummaryApi }): JSX.Element {
    const messages = `${summary.message_count} message${summary.message_count === 1 ? '' : 's'}`
    const firstPermalink = summary.messages?.[0]?.permalink
    return (
        <span className="whitespace-nowrap">
            {firstPermalink ? (
                <Link to={firstPermalink} target="_blank" className="underline decoration-dotted">
                    {messages}
                </Link>
            ) : (
                messages
            )}{' '}
            · generated <TZLabel time={summary.generated_at} />
        </span>
    )
}

function SummaryState({
    title,
    detail,
    children,
}: {
    title: string
    detail: string
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-4">
            <span className="font-semibold">{title}</span>
            <p className="text-secondary text-sm mb-0">{detail}</p>
            {children}
        </div>
    )
}

export function AccountSummaryWidget({ accountId, onRemove }: AccountSummaryWidgetProps): JSX.Element {
    const logic = accountSummariesLogic({ accountId })
    const { summariesResult, summariesResultLoading, generatingFirstSummary } = useValues(logic)
    const { loadSummaries } = useActions(logic)

    const latest = summariesResult.summaries?.[0] ?? null

    let body: JSX.Element
    if (summariesResult === NOT_LOADED) {
        body = <LemonSkeleton className="h-24 w-full m-4" />
    } else if (summariesResult.loadFailed) {
        body = (
            <SummaryState
                title="Couldn't load the summary"
                detail="Something went wrong loading this account's channel summaries. Try refreshing the page."
            />
        )
    } else if (!summariesResult.slackChannelId) {
        body = (
            <SummaryState
                title="No Slack channel linked"
                detail="Link a Slack channel in the account's links to get periodic AI summaries of it here."
            />
        )
    } else if (!latest) {
        body = generatingFirstSummary ? (
            <SummaryState title="Generating the first summary" detail="This usually takes a minute.">
                <Spinner className="text-xl" />
            </SummaryState>
        ) : (
            <SummaryState
                title={summariesResult.cadence ? 'No summaries yet' : 'Summaries are off'}
                detail={
                    summariesResult.cadence
                        ? 'The first summary will appear once the current period closes.'
                        : "Pick a cadence to get periodic AI summaries of this account's Slack channel."
                }
            >
                <AccountSummaryCadencePicker accountId={accountId} />
            </SummaryState>
        )
    } else {
        body = (
            <LemonMarkdown lowKeyHeadings disableImages disableDocsRedirect className="text-sm px-3 py-3">
                {latest.content}
            </LemonMarkdown>
        )
    }

    return (
        <AccountWidgetCard
            wide
            icon={<IconSparkles />}
            title="Account summary"
            titleExtra={
                summariesResult.cadence ? (
                    <LemonTag type="default" size="small">
                        {summariesResult.cadence}
                    </LemonTag>
                ) : null
            }
            meta={latest ? <SummaryMeta summary={latest} /> : null}
            onRefresh={summariesResultLoading ? undefined : loadSummaries}
            onRemove={onRemove}
            data-attr="account-summary-widget"
        >
            {body}
        </AccountWidgetCard>
    )
}
