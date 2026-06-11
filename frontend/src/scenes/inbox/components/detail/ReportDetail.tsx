import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconDocument, IconSearch } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SignalNode } from 'scenes/debug/signals/types'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { SignalReport } from '../../types'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import { DetailSection, RightColumnSection } from './DetailSection'
import { ReportDetailActions } from './ReportDetailActions'
import { ReportTasksSection } from './ReportTasksSection'
import { SuggestedReviewersSection } from './SuggestedReviewersSection'

/** Status / priority / actionability badges for a report's detail header. Mirrors desktop `InboxDetailFrame`. */
export function ReportDetailBadges({ report }: { report: SignalReport }): JSX.Element {
    return (
        <>
            <SignalReportPriorityBadge priority={report.priority} />
            {/* "Ready" is the default terminal state; once actionability is known, surface that instead. */}
            {(report.status !== 'ready' || !report.actionability) && <SignalReportStatusBadge status={report.status} />}
            <SignalReportActionabilityBadge actionability={report.actionability} />
        </>
    )
}

interface InboxDetailFrameProps {
    report: SignalReport
    /** Summary section heading icon + title. */
    summary: { icon: ReactNode; title: string }
    /** Extra primary action(s) rendered after the shared report actions. */
    primaryAction?: ReactNode
    /** Extra sections (Tasks, Reviewers) — defaults applied by callers. */
    children?: ReactNode
}

/**
 * Shared chrome for the Report and Pull request detail bodies: summary on the left, supporting
 * sections (Evidence, Runs, Reviewers) on the right. Mirrors desktop `InboxDetailFrame`.
 * AgentRunDetail keeps its own layout. The page header/back-link chrome is owned by the shell.
 */
export function InboxDetailFrame({ report, summary, primaryAction, children }: InboxDetailFrameProps): JSX.Element {
    const { reportSignals, reportSignalsLoading } = useValues(inboxReportDetailLogic({ reportId: report.id }))
    const signals = reportSignals ?? []
    const evidenceCount = reportSignals !== null ? signals.length : report.signal_count
    const hasEvidence = evidenceCount > 0

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <div className="flex items-center gap-2 flex-wrap mb-4">
                <ReportDetailBadges report={report} />
                <div className="flex-1" />
                <div className="flex items-center gap-2 shrink-0">
                    <ReportDetailActions report={report} />
                    {primaryAction}
                </div>
            </div>

            <div className="grid grid-cols-1 @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] gap-5">
                <div className="min-w-0">
                    <DetailSection icon={summary.icon} title={summary.title}>
                        {report.summary ? (
                            <LemonMarkdown className="text-sm text-secondary leading-normal">
                                {report.summary}
                            </LemonMarkdown>
                        ) : (
                            <p className="text-sm text-tertiary m-0">
                                No summary yet – an agent is still investigating.
                            </p>
                        )}
                    </DetailSection>
                </div>

                <div className="flex flex-col min-w-0 gap-5">
                    {hasEvidence && (
                        <RightColumnSection
                            icon={<IconSearch />}
                            title="Evidence"
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
                    <ReportTasksSection report={report} />
                    <SuggestedReviewersSection report={report} />
                    {children}
                </div>
            </div>
        </div>
    )
}

export function ReportDetail({ report }: { report: SignalReport }): JSX.Element {
    return <InboxDetailFrame report={report} summary={{ icon: <IconDocument />, title: 'Summary' }} />
}
