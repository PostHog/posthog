import { LemonCollapse, LemonTag, Link } from '@posthog/lemon-ui'

import { stripMarkdown } from 'lib/utils/markdown'
import { urls } from 'scenes/urls'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

interface LinkedReportsPanelProps {
    linkedReports: SignalReportApi[]
    linkedReportsLoading?: boolean
}

function statusTagType(status: string): 'success' | 'primary' | 'warning' | 'default' {
    switch (status) {
        case 'ready':
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

function statusLabel(status: string): string {
    return status.replace(/_/g, ' ')
}

/** Report summaries are long and sectioned (`## Problem`, `## Impact`). Stripping markdown across the
 * whole thing runs the heading words into the prose, so preview the lead paragraph only. */
function summaryPreview(summary: string): string {
    return stripMarkdown(summary.split(/\n\s*\n/)[0] ?? '').trim()
}

export function LinkedReportsPanel({ linkedReports, linkedReportsLoading }: LinkedReportsPanelProps): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            // Open when there is something to read, so a teammate sees the findings without a click.
            // Stays shut when empty, where the header alone says all there is to say.
            defaultActiveKey={linkedReports.length > 0 ? 'linked-reports' : undefined}
            panels={[
                {
                    key: 'linked-reports',
                    header: (
                        <>
                            What Self-driving found
                            {linkedReports.length > 0 && (
                                <span className="text-muted-alt font-normal ml-1">({linkedReports.length})</span>
                            )}
                        </>
                    ),
                    content: (
                        <div className="space-y-2">
                            {linkedReportsLoading ? (
                                <div className="text-muted-alt text-xs">Looking for findings...</div>
                            ) : linkedReports.length === 0 ? (
                                <div className="text-muted-alt text-xs">
                                    Nothing investigated for this ticket yet. Findings appear here once Self-driving has
                                    looked into it.
                                </div>
                            ) : (
                                <div className="space-y-2 max-h-96 overflow-auto">
                                    {linkedReports.map((report) => (
                                        <div
                                            key={report.id}
                                            className="p-2 mb-2 rounded border border-primary hover:border-secondary transition-colors"
                                        >
                                            <div className="flex items-center justify-between gap-2 mb-1">
                                                <Link
                                                    to={urls.inboxReport('reports', report.id)}
                                                    className="text-xs font-medium"
                                                >
                                                    {report.title || 'Untitled finding'}
                                                </Link>
                                                <LemonTag size="small" type={statusTagType(report.status)}>
                                                    {statusLabel(report.status)}
                                                </LemonTag>
                                            </div>
                                            {report.summary && (
                                                <div className="text-xs text-muted line-clamp-3 mb-1">
                                                    {summaryPreview(report.summary)}
                                                </div>
                                            )}
                                            {report.implementation_pr_url && (
                                                <Link
                                                    to={report.implementation_pr_url}
                                                    target="_blank"
                                                    className="text-xs"
                                                >
                                                    View proposed fix
                                                </Link>
                                            )}
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
