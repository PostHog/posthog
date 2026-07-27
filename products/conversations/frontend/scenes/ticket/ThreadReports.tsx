import { Link, Tooltip } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { TZLabel } from 'lib/components/TZLabel'
import { derivePrState, type PrBadgeState } from 'lib/signals/prState'
import { PrBadge } from 'lib/signals/SignalReportPrBadge'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { STATUS_LABELS, STATUS_TOOLTIPS } from '~/scenes/inbox/components/badges/SignalReportStatusBadge'
import type { SignalReportStatus } from '~/scenes/inbox/types'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
    parsePrUrlParts,
    safeHttpUrl,
} from '~/scenes/inbox/utils/reportPresentation'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import type { TimelineExtra } from '../../components/Chat/MessageList'
import { TeamOnlyBadge } from '../../components/Chat/TeamOnlyBadge'

/** The inbox's own labels are written to stand alone in a badge, so this surface phrases the same
 * states as a sentence a teammate can act on. The state derivation stays shared. */
const FIX_LABEL: Record<PrBadgeState, string> = {
    open: 'Fix proposed',
    merged: 'Fix merged',
    closed: 'Fix closed',
}

/**
 * Whether it shipped, which is what a teammate answering the customer most needs. A pull request says
 * that better than the report's own status, so the status is the fallback rather than a second badge:
 * either there's no PR, or its URL doesn't parse as one.
 *
 * `PrBadge` brings the link, state colour, and the external-link and accessibility handling the inbox
 * already got right.
 */
function FixOrStatus({ report }: { report: SignalReportApi }): JSX.Element {
    // The URL comes from an agent's raw task-run output and isn't scheme-validated server-side.
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const prNumber = prUrl ? parsePrUrlParts(prUrl)?.number : undefined
    if (prUrl && prNumber) {
        const state = derivePrState(report.status, report.implementation_pr_merged)
        return (
            <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold">{FIX_LABEL[state]}</span>
                <PrBadge prNumber={prNumber} prUrl={prUrl} state={state} />
            </div>
        )
    }
    const statusKey = report.status as SignalReportStatus
    const label = STATUS_LABELS[statusKey] ?? report.status
    // The inbox badge always explains itself on hover, falling back to the label; match that.
    return (
        <Tooltip title={STATUS_TOOLTIPS[statusKey] ?? label}>
            <span className="text-xs text-muted-alt">{label}</span>
        </Tooltip>
    )
}

/**
 * One report, as an entry in the ticket thread.
 *
 * The thread is a place where people talk to customers, so this has to read as three things at a
 * glance: not a person, not sent to anyone, and about this conversation. It wears the PostHog mark
 * instead of an avatar, names the agent rather than a human, keeps the thread's own private-note
 * lock, and deliberately avoids the message bubble so it doesn't scan as something anybody said.
 */
export function ThreadReportEntry({ report }: { report: SignalReportApi }): JSX.Element {
    const headline = deriveHeadline(report.summary)
    // Full width, unlike a message: messages are inset because they belong to one side of the
    // conversation, and this belongs to neither.
    return (
        <div className="mb-4">
            {/* Same header structure as a message: who on the left, then the facts about this entry
                clustered on the right, so the thread keeps one rhythm down the page. */}
            <div className="flex items-center justify-between w-full gap-2 mb-1">
                <div className="flex items-center gap-1.5 min-w-0">
                    {/* The PostHog mark rather than an avatar: this is our software acting, not a
                        teammate with a profile. Mono and theme-following so it reads as a byline next to
                        the name instead of competing with it. Height comes from a class because the size
                        tokens start at 20px, and it lands just under a message avatar's 18px: small
                        enough to sit on the same rhythm, big enough to still read as the PostHog mark. */}
                    <Logomark variant="mono" color="primary" className="h-4 w-auto shrink-0" />
                    <span className="text-sm font-medium">Self-driving</span>
                    <Tooltip title="A PostHog agent that investigates tickets against your codebase. Not a teammate.">
                        <span className="text-xs text-muted-alt">PostHog agent</span>
                    </Tooltip>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                    <TeamOnlyBadge label="Internal" />
                    <span className="text-xs text-muted-alt">
                        <TZLabel time={report.updated_at} />
                    </span>
                </div>
            </div>
            {/* Not a bubble, and marked down its edge, so it never reads as something a person said.
                The edge is a pseudo-element so it can run the full height without fighting the border
                radius the way a left border does. */}
            <div className="relative flex items-start justify-between gap-3 overflow-hidden rounded border border-primary bg-surface-primary transition-colors hover:border-secondary py-2 pl-4 pr-3 after:content-[''] after:absolute after:inset-y-0 after:left-0 after:w-1 after:bg-accent">
                {/* The link takes the whole left column so the entry reads as one target, while the
                    state stays a sibling: an anchor can't contain another, and clicking the pull
                    request should open the pull request. */}
                <Link
                    to={urls.inboxReport('reports', report.id)}
                    className="block min-w-0 flex-1 text-inherit no-underline hover:text-inherit"
                >
                    <div className="text-sm font-semibold leading-snug">
                        {capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))}
                    </div>
                    {headline && <p className="mt-0.5 mb-0 text-xs text-muted leading-snug">{headline}</p>}
                </Link>
                <div className="shrink-0">
                    <FixOrStatus report={report} />
                </div>
            </div>
        </div>
    )
}

/** Reports as thread entries, ordered by when each was last updated. */
export function reportTimelineExtras(linkedReports: SignalReportApi[]): TimelineExtra[] {
    return linkedReports.map((report) => ({
        at: report.updated_at,
        element: <ThreadReportEntry key={report.id} report={report} />,
    }))
}
