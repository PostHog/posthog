import { useValues } from 'kea'

import {
    IconArrowRight,
    IconCheckCircle,
    IconClock,
    IconDocument,
    IconPullRequest,
    IconSearch,
    IconWarning,
} from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { SignalReport, SignalReportStatus } from '../../types'
import { deriveHeadline, parsePrRepoSlug } from '../../utils/reportPresentation'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { DetailSection, RightColumnSection } from './DetailSection'
import { ReportDetailBadges } from './ReportDetail'
import { ReportTasksSection } from './ReportTasksSection'

/** Pull the `#1234` PR number out of a GitHub PR URL. */
function parsePrNumber(prUrl: string): string | null {
    try {
        const match = new URL(prUrl).pathname.match(/\/pull\/(\d+)(?:$|[/?#])/)
        return match ? match[1] : null
    } catch {
        return null
    }
}

/**
 * Ready-state run output: a polished outcome card that links to the produced PR or report,
 * mirroring desktop `RunOutputReadyCard`. Status glyph, PR ref / source, headline, and a
 * call-to-action to open the result.
 */
function RunOutputReadyCard({ report }: { report: SignalReport }): JSX.Element {
    const prUrl = report.implementation_pr_url ?? null
    const isPr = !!prUrl
    const prSlug = prUrl ? parsePrRepoSlug(prUrl) : null
    const prNumber = prUrl ? parsePrNumber(prUrl) : null
    const sourceMeta = getSourceProductMeta(report.source_products?.[0])
    const headline = report.title || deriveHeadline(report.summary)

    return (
        <Link
            to={urls.inboxReport(isPr ? 'pulls' : 'reports', report.id)}
            className="group flex flex-col gap-2 rounded border border-primary bg-surface-primary px-4 py-3.5 no-underline text-inherit transition-colors duration-150 hover:border-primary hover:bg-surface-secondary"
        >
            <div className="flex items-center gap-2 flex-wrap">
                <span className="flex items-center justify-center size-5 shrink-0 rounded-full bg-success-highlight text-success">
                    {isPr ? <IconPullRequest className="text-xs" /> : <IconCheckCircle className="text-xs" />}
                </span>
                {prSlug && prNumber ? (
                    <span className="font-mono text-[12.5px] text-primary">
                        {prSlug}#{prNumber}
                    </span>
                ) : (
                    <span className="font-medium text-sm text-primary">Report ready</span>
                )}
                <span className="flex-1" />
                {sourceMeta ? (
                    <span className="flex items-center gap-1.5 text-xs text-tertiary">
                        <span className="flex shrink-0 items-center" style={{ color: sourceMeta.color }} aria-hidden>
                            <sourceMeta.Icon className="text-sm" />
                        </span>
                        <span>{sourceMeta.label}</span>
                    </span>
                ) : null}
            </div>
            {headline ? (
                <span className="line-clamp-2 text-[12.5px] text-secondary leading-snug">{headline}</span>
            ) : null}
            <span className="flex items-center gap-1 text-xs text-tertiary">
                {isPr ? 'Open the pull request' : 'Open the report'}
                <IconArrowRight className="transition-transform group-hover:translate-x-0.5" />
            </span>
        </Link>
    )
}

/**
 * Run-output widget: the headline state of an agent run. Ready → outcome card (PR/report);
 * failed → error banner; in-progress / queued → draft summary that fills in live.
 * Mirrors desktop `RunOutputWidget`.
 */
function RunOutputWidget({ report }: { report: SignalReport }): JSX.Element {
    if (report.status === SignalReportStatus.READY || report.implementation_pr_url) {
        return <RunOutputReadyCard report={report} />
    }

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
 * Compact run-state strip: live/finished status, the produced branch (when a PR exists), and run
 * timing. Mirrors desktop's run-state header line (status · branch · timing) without rebuilding the
 * run log — the actual log lives behind the linked runs (see `ReportTasksSection`).
 */
function RunStateStrip({ report }: { report: SignalReport }): JSX.Element {
    const isLive =
        report.status === SignalReportStatus.IN_PROGRESS || report.status === SignalReportStatus.PENDING_INPUT
    const isFailed = report.status === SignalReportStatus.FAILED
    const prSlug = report.implementation_pr_url ? parsePrRepoSlug(report.implementation_pr_url) : null
    const timestamp = report.updated_at ?? report.created_at

    return (
        <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-xs text-tertiary">
            <span className="flex items-center gap-1.5 font-medium text-secondary">
                <span
                    className={
                        'inline-block size-1.5 shrink-0 rounded-full ' +
                        (isFailed ? 'bg-danger' : isLive ? 'bg-primary animate-pulse' : 'bg-success')
                    }
                    aria-hidden
                />
                {isFailed ? 'Failed' : isLive ? 'Running' : 'Finished'}
            </span>
            {prSlug ? (
                <span className="flex items-center gap-1 font-mono">
                    <IconPullRequest className="text-sm" />
                    {prSlug}
                </span>
            ) : null}
            <span className="flex items-center gap-1">
                <IconClock className="text-sm" />
                <span>{isLive ? 'Started' : 'Updated'}</span>
                <TZLabel time={timestamp} />
            </span>
        </div>
    )
}

/**
 * Agent run detail body. Shows the run state strip + output state, the linked run(s) (which link out
 * to the task detail page — we do NOT rebuild the run-log viewer here), and contributing evidence.
 * Mirrors desktop `AgentRunDetail`'s intent with cloud's existing task-detail run log.
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
                    <RunStateStrip report={report} />
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
