import { BindLogic, useValues } from 'kea'

import { IconExternal, IconTrending } from '@posthog/icons'
import { LemonSkeleton, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssueListRow } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList'
import type { ErrorTrackingSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import {
    inboxErrorTrackingIssueLogic,
    InboxErrorTrackingIssueLogicProps,
    InboxErrorTrackingIssueSourceType,
} from './inboxErrorTrackingIssueLogic'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a signal's `extra` to the error tracking shape (a string `fingerprint`). */
export function isErrorTrackingExtra(value: unknown): value is Record<string, unknown> & ErrorTrackingSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.fingerprint === 'string'
}

interface SourceTypeBadge {
    label: string
    type: LemonTagType
    icon?: JSX.Element
}

const SOURCE_TYPE_BADGES: Record<InboxErrorTrackingIssueSourceType, SourceTypeBadge> = {
    issue_created: { label: 'New issue', type: 'primary' },
    issue_reopened: { label: 'Reopened', type: 'warning' },
    issue_spiking: { label: 'Spiking', type: 'danger', icon: <IconTrending /> },
}

function asSourceType(sourceType: string): InboxErrorTrackingIssueSourceType {
    return sourceType === 'issue_reopened' || sourceType === 'issue_spiking' ? sourceType : 'issue_created'
}

/** Footer link out to the full error tracking issue scene. */
function ViewIssueLink({ issueId, fingerprint }: { issueId: string; fingerprint: string }): JSX.Element {
    return (
        <Link
            to={urls.errorTrackingIssue(issueId, { fingerprint })}
            target="_blank"
            className="flex items-center gap-1 text-xs font-medium shrink-0"
        >
            View issue <IconExternal className="size-3" />
        </Link>
    )
}

/** Inner body: reads the loaded issue from the bound logic and renders the live row, skeleton, or fallback. */
function ErrorTrackingSignalCardBody({
    signal,
    fingerprint,
}: {
    signal: SignalNode
    fingerprint: string
}): JSX.Element {
    const { mergedIssue, issueLoading, summaryLoading, summaryUnavailable, mergedFailed, mergedToIssueId } =
        useValues(inboxErrorTrackingIssueLogic)

    const linkIssueId = mergedToIssueId ?? signal.source_id

    if (mergedFailed) {
        // Issue not found or merged away – degrade to a thin fallback with just the fingerprint and a link.
        return (
            <div className="flex items-center gap-2 text-xs text-tertiary">
                <span className="font-mono truncate">{fingerprint}</span>
                <span className="flex-1" />
                <ViewIssueLink issueId={linkIssueId} fingerprint={fingerprint} />
            </div>
        )
    }

    if (!mergedIssue || (issueLoading && summaryLoading)) {
        return <LemonSkeleton className="h-16 w-full" />
    }

    return (
        <div className="rounded border bg-surface-primary">
            <ErrorTrackingIssueListRow issue={mergedIssue} canMutateIssues={false} />
            {summaryUnavailable && (
                // The aggregation summary was throttled/unavailable; the row still renders without a sparkline.
                <div className="px-2 pb-1 text-xs text-tertiary">Summary unavailable right now</div>
            )}
        </div>
    )
}

/** Inbox signal card for error tracking issues: embeds the live issue row read-only. */
export function ErrorTrackingSignalCard({ signal }: SignalCardProps): JSX.Element {
    const fingerprint = isErrorTrackingExtra(signal.extra) ? signal.extra.fingerprint : ''
    const sourceType = asSourceType(signal.source_type)
    const badge = SOURCE_TYPE_BADGES[sourceType]

    const logicProps: InboxErrorTrackingIssueLogicProps = {
        issueId: signal.source_id,
        fingerprint,
        sourceType,
    }

    return (
        <SignalCardShell
            signal={signal}
            rightSlot={
                <LemonTag type={badge.type} size="small" icon={badge.icon}>
                    {badge.label}
                </LemonTag>
            }
        >
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            <BindLogic logic={inboxErrorTrackingIssueLogic} props={logicProps}>
                <ErrorTrackingSignalCardBody signal={signal} fingerprint={fingerprint} />
            </BindLogic>

            <div className="flex items-center gap-2 text-xs text-tertiary mt-2">
                <span className="flex-1" />
                <ViewIssueLink issueId={signal.source_id} fingerprint={fingerprint} />
            </div>
        </SignalCardShell>
    )
}

export const errorTrackingSignalCardEntry: SignalCardEntry = {
    key: 'error_tracking',
    matches: (signal) => signal.source_product === 'error_tracking' && isErrorTrackingExtra(signal.extra),
    Component: ErrorTrackingSignalCard,
}
