import { Link, Tooltip } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { TZLabel } from 'lib/components/TZLabel'
import { SignalReportFixOrStatus } from 'lib/signals/SignalReportFixOrStatus'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
} from 'products/signals/frontend/inbox/utils/reportPresentation'

import type { TimelineExtra } from '../../components/Chat/MessageList'
import { TeamOnlyBadge } from '../../components/Chat/TeamOnlyBadge'

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
                    {/* The name takes the AI colour, the same one the assistant's byline and notes wear
                        in this thread. "PostHog agent" stays muted: it qualifies the name rather than
                        repeating it. */}
                    <span className="text-sm font-medium text-ai">Self-driving</span>
                    <Tooltip title="A PostHog agent that investigates tickets against your codebase. Not a teammate.">
                        <span className="text-xs text-muted-alt">PostHog agent</span>
                    </Tooltip>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                    <TeamOnlyBadge label="Internal" tone="agent" />
                    <span className="text-xs text-muted-alt">
                        <TZLabel time={report.updated_at} />
                    </span>
                </div>
            </div>
            {/* Not a bubble, and marked down its edge, so it never reads as something a person said.
                The edge is a pseudo-element so it can run the full height without fighting the border
                radius the way a left border does. It carries the AI colour, the same one the
                assistant's own internal notes wear in this thread, so everything our software leaves
                on a ticket reads as one voice — distinct from a teammate's amber note. */}
            <div className="relative flex items-start justify-between gap-3 overflow-hidden rounded border border-primary bg-surface-primary transition-colors hover:border-secondary py-2 pl-4 pr-3 after:content-[''] after:absolute after:inset-y-0 after:left-0 after:w-1 after:bg-ai">
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
                    <SignalReportFixOrStatus report={report} />
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
