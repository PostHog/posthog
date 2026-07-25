import { IconPullRequest } from '@posthog/icons'
import { LemonCollapse, LemonTag, Link } from '@posthog/lemon-ui'

import { stripMarkdown } from 'lib/utils/markdown'
import { urls } from 'scenes/urls'

import { derivePrState, type PrBadgeState } from '~/scenes/inbox/components/badges/prState'
import { parsePrUrlParts } from '~/scenes/inbox/utils/reportPresentation'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

interface LinkedReportsPanelProps {
    linkedReports: SignalReportApi[]
    linkedReportsLoading?: boolean
}

function statusTagType(status: string): 'success' | 'primary' | 'warning' | 'default' {
    switch (status) {
        case 'resolved':
            return 'success'
        case 'in_progress':
        case 'candidate':
            return 'primary'
        case 'pending_input':
            return 'warning'
        default:
            return 'default'
    }
}

/** Report summaries are long and sectioned (`## Problem`, `## Impact`). Stripping markdown across the
 * whole thing runs the heading words into the prose, so preview the lead paragraph only. */
function summaryPreview(summary: string): string {
    return stripMarkdown(summary.split(/\n\s*\n/)[0] ?? '').trim()
}

/** The inbox's own labels are written to stand alone in a badge, so this surface phrases the same
 * states as a sentence a teammate can act on. The state derivation stays shared. */
const FIX_LABEL: Record<PrBadgeState, string> = {
    open: 'Fix proposed',
    merged: 'Fix merged',
    closed: 'Fix closed',
}

/** The fix itself, which is what a teammate answering the customer most needs. */
function FixLink({ report }: { report: SignalReportApi }): JSX.Element | null {
    if (!report.implementation_pr_url) {
        return null
    }
    const state = derivePrState(report.status, report.implementation_pr_merged)
    const number = parsePrUrlParts(report.implementation_pr_url)?.number
    return (
        <Link to={report.implementation_pr_url} target="_blank" className="flex items-center gap-1 text-xs font-medium">
            <IconPullRequest />
            <span>{FIX_LABEL[state]}</span>
            {number && <span className="text-muted-alt font-normal">#{number}</span>}
        </Link>
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
                                <span className="text-muted-alt font-normal ml-1">({linkedReports.length})</span>
                            )}
                        </>
                    ),
                    content: (
                        <div className="space-y-2">
                            {linkedReportsLoading ? (
                                <div className="text-muted-alt text-xs">Loading reports...</div>
                            ) : linkedReports.length === 0 ? (
                                <div className="text-muted-alt text-xs">No reports linked to this ticket yet.</div>
                            ) : (
                                <div className="space-y-2 max-h-96 overflow-auto">
                                    {linkedReports.map((report) => (
                                        <div
                                            key={report.id}
                                            className="p-2 mb-2 rounded border border-primary hover:border-secondary transition-colors"
                                        >
                                            <div className="flex items-start justify-between gap-2 mb-1">
                                                <Link
                                                    to={urls.inboxReport('reports', report.id)}
                                                    className="text-xs font-medium"
                                                >
                                                    {report.title || 'Untitled report'}
                                                </Link>
                                                {/* A pull request answers "is this fixed?" better than the
                                                    report's own status, so only badge the status without one. */}
                                                {!report.implementation_pr_url && (
                                                    <LemonTag size="small" type={statusTagType(report.status)}>
                                                        {report.status.replace(/_/g, ' ')}
                                                    </LemonTag>
                                                )}
                                            </div>
                                            {report.summary && (
                                                <div className="text-xs text-muted line-clamp-3 mb-1">
                                                    {summaryPreview(report.summary)}
                                                </div>
                                            )}
                                            <FixLink report={report} />
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
