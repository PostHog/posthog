import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconDocument, IconSearch } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SignalNode } from 'scenes/debug/signals/types'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { SignalReport, SignalReportStatus } from '../../types'
import { ForYouBadge } from '../badges/ForYouBadge'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import { getSourceProductMeta, hasKnownSourceProduct } from '../badges/sourceProductIcons'
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
            {report.is_suggested_reviewer && <ForYouBadge />}
        </>
    )
}

/**
 * Compact meta row shown under the detail badges: finding count · last-updated time · source stack.
 * Mirrors desktop `InboxDetailFrame`'s meta row. `evidenceCount` switches to the live signal count
 * once findings load, so the row reads the same whether or not the signals query has resolved.
 */
function ReportDetailMeta({ report, evidenceCount }: { report: SignalReport; evidenceCount: number }): JSX.Element {
    const hasSource = hasKnownSourceProduct(report.source_products)
    return (
        <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary leading-none select-none">
            {evidenceCount > 0 && (
                <>
                    <span className="tabular-nums">
                        {evidenceCount} finding{evidenceCount === 1 ? '' : 's'}
                    </span>
                    <span aria-hidden>·</span>
                </>
            )}
            <TZLabel time={report.updated_at ?? report.created_at} />
            {hasSource && (
                <>
                    <span aria-hidden>·</span>
                    <MetaSourceStack sourceProducts={report.source_products} />
                </>
            )}
        </div>
    )
}

/** Source-product icon stack, prefixed with "agent ·", reused inside the detail meta row. */
function MetaSourceStack({ sourceProducts }: { sourceProducts?: string[] | null }): JSX.Element | null {
    const items = (sourceProducts ?? [])
        .map((key) => ({ key, meta: getSourceProductMeta(key) }))
        .filter(
            (entry): entry is { key: string; meta: NonNullable<ReturnType<typeof getSourceProductMeta>> } =>
                entry.meta !== null
        )
    if (items.length === 0) {
        return null
    }
    const primary = items[0]
    const overflow = items.slice(1)
    return (
        <span className="inline-flex items-center gap-1.5 min-w-0">
            <span>agent ·</span>
            <span className="inline-flex items-center gap-1 shrink-0">
                {items.map((entry) => {
                    const Icon = entry.meta.Icon
                    return (
                        <span
                            key={entry.key}
                            className="inline-flex shrink-0 items-center"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ color: entry.meta.color }}
                            aria-hidden
                        >
                            <Icon className="text-xs" />
                        </span>
                    )
                })}
            </span>
            <span>
                {primary.meta.label}
                {overflow.length > 0 ? ` + ${overflow.length}` : null}
            </span>
        </span>
    )
}

/** Placeholder finding rows shown while the signals query is in flight, sized to the known count. */
function EvidenceSkeleton({ count }: { count: number }): JSX.Element {
    const rows = Math.max(1, Math.min(count, 4))
    return (
        <div className="flex flex-col gap-3" aria-hidden>
            {Array.from({ length: rows }).map((_, i) => (
                <div
                    key={i}
                    className="flex flex-col gap-2 rounded border border-primary bg-surface-primary px-3 py-2.5"
                >
                    <div className="h-3 w-1/3 rounded bg-fill-highlight-100 animate-pulse" />
                    <div className="h-2.5 w-4/5 rounded bg-fill-highlight-50 animate-pulse" />
                </div>
            ))}
        </div>
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

    const summaryPending =
        report.status === SignalReportStatus.IN_PROGRESS || report.status === SignalReportStatus.CANDIDATE

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <div className="flex items-start gap-3 flex-wrap mb-5">
                <div className="flex flex-col gap-2 min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <ReportDetailBadges report={report} />
                    </div>
                    <ReportDetailMeta report={report} evidenceCount={evidenceCount} />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <ReportDetailActions report={report} />
                    {primaryAction}
                </div>
            </div>

            <div className="grid grid-cols-1 @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] gap-5">
                <div className="min-w-0">
                    <DetailSection icon={summary.icon} title={summary.title}>
                        {report.summary ? (
                            <LemonMarkdown className="text-sm text-secondary leading-normal break-words">
                                {report.summary}
                            </LemonMarkdown>
                        ) : (
                            <p className={`text-sm text-tertiary m-0${summaryPending ? ' italic' : ''}`}>
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
                                <EvidenceSkeleton count={evidenceCount} />
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
