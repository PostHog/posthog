import { IconLock, IconPullRequest } from '@posthog/icons'
import { Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { derivePrState, type PrBadgeState } from '~/scenes/inbox/components/badges/prState'
import { STATUS_LABELS, STATUS_TOOLTIPS } from '~/scenes/inbox/components/badges/SignalReportStatusBadge'
import type { SignalReportStatus } from '~/scenes/inbox/types'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
    parsePrUrlParts,
    safeHttpUrl,
} from '~/scenes/inbox/utils/reportPresentation'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

interface ThreadReportsProps {
    linkedReports: SignalReportApi[]
}

/** The inbox's own labels are written to stand alone in a badge, so this surface phrases the same
 * states as a sentence a teammate can act on. The state derivation stays shared. */
const FIX_LABEL: Record<PrBadgeState, string> = {
    open: 'Fix proposed',
    merged: 'Fix merged',
    closed: 'Fix closed',
}

function FixLink({ prUrl, report }: { prUrl: string; report: SignalReportApi }): JSX.Element {
    const number = parsePrUrlParts(prUrl)?.number
    return (
        <Link to={prUrl} target="_blank" className="inline-flex items-center gap-1 text-sm font-semibold">
            <IconPullRequest className="shrink-0" />
            <span>{FIX_LABEL[derivePrState(report.status, report.implementation_pr_merged)]}</span>
            {number && <span className="font-normal text-muted-alt">#{number}</span>}
        </Link>
    )
}

function ReportBody({ report }: { report: SignalReportApi }): JSX.Element {
    // The URL comes from an agent's raw task-run output and isn't scheme-validated server-side.
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const headline = deriveHeadline(report.summary)
    const statusKey = report.status as SignalReportStatus
    const statusTooltip = STATUS_TOOLTIPS[statusKey]
    const status = <span className="text-xs text-muted-alt">{STATUS_LABELS[statusKey] ?? report.status}</span>
    return (
        <div>
            <Link subtle to={urls.inboxReport('reports', report.id)} className="block text-sm font-semibold">
                {capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))}
            </Link>
            {headline && <p className="mt-0.5 mb-0 text-sm text-muted">{headline}</p>}
            <div className="mt-1">
                {/* A pull request answers "did this ship?" better than the report's own status, so the
                    status only speaks for a report without one. */}
                {prUrl ? (
                    <FixLink prUrl={prUrl} report={report} />
                ) : statusTooltip ? (
                    <Tooltip title={statusTooltip}>{status}</Tooltip>
                ) : (
                    status
                )}
            </div>
        </div>
    )
}

/**
 * What Self-driving found, as an entry in the ticket thread rather than sidebar metadata.
 *
 * A researched report is something that happened to this conversation, so it belongs in the
 * conversation, at the end where the person about to reply is already looking. It borrows the
 * thread's existing private-note affordance so it reads unmistakably as internal: nothing here
 * was sent to the customer.
 */
export function ThreadReports({ linkedReports }: ThreadReportsProps): JSX.Element | null {
    if (linkedReports.length === 0) {
        return null
    }
    return (
        <div className="px-1 pt-1">
            <div className="flex items-center gap-1.5 mb-1">
                <ProfilePicture size="sm" name="Self-driving" type="bot" showName={true} />
                <Tooltip title="Only visible to your team">
                    <span className="inline-flex items-center gap-0.5 text-xs text-warning-dark bg-warning-highlight px-1.5 py-0.5 rounded">
                        <IconLock className="text-xs" />
                        Internal
                    </span>
                </Tooltip>
            </div>
            <div className="min-w-0">
                <div className="rounded border border-primary bg-surface-primary divide-y divide-primary">
                    {linkedReports.map((report) => (
                        <div key={report.id} className="px-3 py-2">
                            <ReportBody report={report} />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
