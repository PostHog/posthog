import { IconPullRequest } from '@posthog/icons'
import { LemonCollapse, Link, Tooltip } from '@posthog/lemon-ui'

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

interface LinkedReportsPanelProps {
    linkedReports: SignalReportApi[]
    linkedReportsLoading?: boolean
}

/** The inbox's own labels are written to stand alone in a badge, so this surface phrases the same
 * states as a sentence a teammate can act on. The state derivation stays shared. */
const FIX_LABEL: Record<PrBadgeState, string> = {
    open: 'Fix proposed',
    merged: 'Fix merged',
    closed: 'Fix closed',
}

/** A report with no fix yet still says something, but quietly: colour belongs to the fix. Labels and
 * explanations come from the inbox so both surfaces describe a report's state with the same words. */
function ReportStatus({ status }: { status: string }): JSX.Element {
    const key = status as SignalReportStatus
    const tooltip = STATUS_TOOLTIPS[key]
    const label = <span className="text-xs text-muted-alt">{STATUS_LABELS[key] ?? status}</span>
    return tooltip ? <Tooltip title={tooltip}>{label}</Tooltip> : label
}

/** The fix is the one thing worth colouring, so it carries the row's only accent. */
function FixLink({ prUrl, report }: { prUrl: string; report: SignalReportApi }): JSX.Element {
    const number = parsePrUrlParts(prUrl)?.number
    return (
        <Link to={prUrl} target="_blank" className="inline-flex items-center gap-1 text-xs font-semibold">
            <IconPullRequest className="shrink-0" />
            <span>{FIX_LABEL[derivePrState(report.status, report.implementation_pr_merged)]}</span>
            {number && <span className="font-normal text-muted-alt">#{number}</span>}
        </Link>
    )
}

function ReportRow({ report }: { report: SignalReportApi }): JSX.Element {
    // The URL comes from an agent's raw task-run output and isn't scheme-validated server-side.
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const headline = deriveHeadline(report.summary)
    return (
        <li className="py-2 first:pt-0 last:pb-0">
            <Link
                subtle
                to={urls.inboxReport('reports', report.id)}
                className="block text-xs font-semibold leading-snug"
            >
                {capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))}
            </Link>
            {headline && <p className="mt-0.5 mb-0 text-xs text-muted leading-snug">{headline}</p>}
            <div className="mt-1">
                {/* One state signal per row: a pull request answers "did this ship?" better than the
                    report's own status, so the status only speaks for a report without one. */}
                {prUrl ? <FixLink prUrl={prUrl} report={report} /> : <ReportStatus status={report.status} />}
            </div>
        </li>
    )
}

export function LinkedReportsPanel({ linkedReports, linkedReportsLoading }: LinkedReportsPanelProps): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            // Open when there is something to read, so a teammate sees the reports without a click.
            // Stays shut when empty, where the header alone says all there is to say.
            // `multiple` because only that variant re-syncs its default keys after mount, and the
            // reports arrive from a request that resolves later than the first render.
            multiple
            defaultActiveKeys={linkedReports.length > 0 ? ['linked-reports'] : []}
            panels={[
                {
                    key: 'linked-reports',
                    header: (
                        <>
                            Associated reports
                            {linkedReports.length > 0 && (
                                <span className="ml-1 font-normal text-muted-alt">({linkedReports.length})</span>
                            )}
                        </>
                    ),
                    content: linkedReportsLoading ? (
                        <div className="text-xs text-muted-alt">Loading reports...</div>
                    ) : linkedReports.length === 0 ? (
                        <div className="text-xs text-muted-alt">No reports linked to this ticket yet.</div>
                    ) : (
                        // Dividers rather than a card per report: one bordered panel is enough chrome
                        // for a sidebar this narrow, and the rows read as one list instead of a stack.
                        <ul className="max-h-96 overflow-auto divide-y divide-primary">
                            {linkedReports.map((report) => (
                                <ReportRow key={report.id} report={report} />
                            ))}
                        </ul>
                    ),
                },
            ]}
        />
    )
}
