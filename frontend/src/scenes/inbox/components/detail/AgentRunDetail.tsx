import { useValues } from 'kea'

import { IconDocument, IconSearch, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SignalNode } from 'scenes/debug/signals/types'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { SignalReport, SignalReportStatus } from '../../types'
import { DetailSection, RightColumnSection } from './DetailSection'
import { ReportDetailBadges } from './ReportDetail'
import { ReportTasksSection } from './ReportTasksSection'

/** Run-output widget: ready / failed / in-progress draft summary. Mirrors desktop `RunOutputWidget`. */
function RunOutputWidget({ report }: { report: SignalReport }): JSX.Element {
    if (report.status === SignalReportStatus.FAILED) {
        return (
            <div className="flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
                <span className="flex items-center justify-center size-9 shrink-0 rounded-full bg-danger-highlight text-danger">
                    <IconWarning className="size-4" />
                </span>
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <span className="font-medium text-sm text-primary">Run failed</span>
                    <span className="text-xs text-secondary leading-snug">
                        Research couldn't complete – check the linked run below for the error. The agent may retry
                        automatically.
                    </span>
                </div>
            </div>
        )
    }

    return (
        <DetailSection icon={<IconDocument />} title="Draft summary">
            {report.summary ? (
                <LemonMarkdown className="text-sm text-secondary leading-normal">{report.summary}</LemonMarkdown>
            ) : (
                <p className="text-sm text-tertiary m-0">
                    {report.status === SignalReportStatus.IN_PROGRESS
                        ? 'The agent is investigating – partial findings will appear here as they land.'
                        : 'Queued for research.'}
                </p>
            )}
        </DetailSection>
    )
}

/**
 * Agent run detail body. Shows the run output state, the linked run(s) (which link out to the task
 * detail page — we do NOT rebuild the run-log viewer here), and contributing evidence. Mirrors
 * desktop `AgentRunDetail`'s intent with cloud's existing task-detail run log.
 */
export function AgentRunDetail({ report }: { report: SignalReport }): JSX.Element {
    const { reportSignals, reportSignalsLoading } = useValues(inboxReportDetailLogic({ reportId: report.id }))
    const signals = reportSignals ?? []
    const evidenceCount = reportSignals !== null ? signals.length : report.signal_count

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <div className="flex items-center gap-2 flex-wrap mb-4">
                <ReportDetailBadges report={report} />
            </div>

            <div className="grid grid-cols-1 @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] gap-5">
                <div className="flex flex-col min-w-0 gap-5">
                    <RunOutputWidget report={report} />
                    <ReportTasksSection report={report} />
                </div>

                <div className="flex flex-col min-w-0 gap-5">
                    {evidenceCount > 0 && (
                        <RightColumnSection
                            icon={<IconSearch />}
                            title="Evidence so far"
                            rightSlot={
                                <span className="text-[0.6875rem] text-tertiary tabular-nums">
                                    {evidenceCount} finding{evidenceCount === 1 ? '' : 's'}
                                </span>
                            }
                        >
                            {reportSignalsLoading && reportSignals === null ? (
                                <div className="flex items-center gap-2 text-xs text-tertiary py-1">
                                    <Spinner className="size-3" />
                                    Loading findings…
                                </div>
                            ) : (
                                <div className="flex flex-col gap-3">
                                    {signals.map((signal: SignalNode) => (
                                        <SignalCard key={signal.signal_id} signal={signal} />
                                    ))}
                                </div>
                            )}
                        </RightColumnSection>
                    )}
                </div>
            </div>
        </div>
    )
}
