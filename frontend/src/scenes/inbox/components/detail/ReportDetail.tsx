import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconArrowLeft, IconCode, IconDocument, IconExternal, IconPullRequest, IconSearch } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { InboxTabKey, INBOX_TAB_LABEL, SignalReport, SignalReportStatus } from '../../types'
import {
    displayConventionalCommitTitle,
    ParsedPrUrlParts,
    parseConventionalCommitTitle,
    parsePrUrlParts,
    safeHttpUrl,
} from '../../utils/reportPresentation'
import { ForYouBadge } from '../badges/ForYouBadge'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import { hasKnownSourceProduct, knownSourceProductEntries, SourceProductIconRow } from '../badges/sourceProductIcons'
import { ConventionalCommitScopeTag } from '../cards/ReportCard'
import { RightColumnSection } from './DetailSection'
import { ReportDetailActions } from './ReportDetailActions'
import { ReportTasksSection } from './ReportTasksSection'
import { SuggestedReviewersSection } from './SuggestedReviewersSection'

/** Status / priority / actionability badges for a report's detail header. Mirrors desktop `InboxDetailFrame`. */
export function ReportDetailBadges({ report }: { report: SignalReport }): JSX.Element {
    return (
        <>
            <SignalReportPriorityBadge priority={report.priority} explanation={report.priority_explanation} />
            {/* "Ready" is the default terminal state; once actionability is known, surface that instead. */}
            {(report.status !== 'ready' || !report.actionability) && <SignalReportStatusBadge status={report.status} />}
            <SignalReportActionabilityBadge
                actionability={report.actionability}
                explanation={report.actionability_explanation}
            />
            {report.is_suggested_reviewer && <ForYouBadge />}
        </>
    )
}

/**
 * Single meta line under the title: status/actionability/for-you chips, then dot-separated stats
 * (finding count · created [· updated] · source stack). The updated time is only shown when
 * it meaningfully differs from created. `evidenceCount` switches to the live signal count once
 * findings load, so the row reads the same before and after the query resolves.
 */
function ReportDetailMeta({ report, evidenceCount }: { report: SignalReport; evidenceCount: number }): JSX.Element {
    const hasSource = hasKnownSourceProduct(report.source_products)
    // "Ready" is the default terminal state; surface the status chip only until actionability is known.
    const showStatus = report.status !== 'ready' || !report.actionability

    const stats: ReactNode[] = []
    if (evidenceCount > 0) {
        stats.push(
            <span className="tabular-nums">
                {evidenceCount} finding{evidenceCount === 1 ? '' : 's'}
            </span>
        )
    }
    // Updated is shown alongside Created only when they differ beyond same-moment noise (≥ 1 min apart).
    const updatedDiffers =
        !!report.updated_at && Math.abs(dayjs(report.updated_at).diff(dayjs(report.created_at), 'minute')) >= 1
    stats.push(
        <span className="flex items-center gap-1">
            <span>Created</span>
            <TZLabel time={report.created_at} />
        </span>
    )
    if (updatedDiffers) {
        stats.push(
            <span className="flex items-center gap-1">
                <span>Updated</span>
                <TZLabel time={report.updated_at} />
            </span>
        )
    }
    if (hasSource) {
        stats.push(<MetaSourceStack sourceProducts={report.source_products} />)
    }

    return (
        <div className="flex items-center gap-x-2 gap-y-1.5 flex-wrap text-xs text-tertiary leading-none select-none">
            {showStatus && <SignalReportStatusBadge status={report.status} />}
            <SignalReportActionabilityBadge
                actionability={report.actionability}
                explanation={report.actionability_explanation}
            />
            {report.is_suggested_reviewer && <ForYouBadge />}
            <span className="flex items-center gap-2 flex-wrap min-w-0">
                {stats.map((node, i) => (
                    <span key={i} className="flex items-center gap-2 min-w-0">
                        {i > 0 && <span aria-hidden>·</span>}
                        {node}
                    </span>
                ))}
            </span>
        </div>
    )
}

/** Source-product icon stack, prefixed with "agent ·", reused inside the detail meta row. */
function MetaSourceStack({ sourceProducts }: { sourceProducts?: string[] | null }): JSX.Element | null {
    const [primary, ...overflow] = knownSourceProductEntries(sourceProducts)
    if (!primary) {
        return null
    }
    return (
        <span className="inline-flex items-center gap-1.5 min-w-0">
            <span>agent ·</span>
            <SourceProductIconRow
                entries={[primary, ...overflow]}
                className="inline-flex items-center gap-1 shrink-0"
            />
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

/**
 * Layout-faithful placeholder shown while a report's base record loads on a cold open (deep link
 * with no list row to seed from). Mirrors `InboxDetailFrame`'s header + two-column shape so the
 * page doesn't jump when the real content lands — and so loading reads as "this view, populating"
 * rather than a bare centered spinner.
 */
export function ReportDetailSkeleton(): JSX.Element {
    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm" aria-hidden>
            <div className="flex flex-col gap-3.5 mb-6 pb-5 border-b border-primary">
                <div className="h-3.5 w-24 rounded bg-fill-highlight-50 animate-pulse" />
                <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                        <div className="size-7 shrink-0 mt-0.5 rounded bg-fill-highlight-100 animate-pulse" />
                        <div className="flex flex-col gap-2 min-w-0 flex-1">
                            <div className="h-6 w-2/3 rounded bg-fill-highlight-100 animate-pulse" />
                            <div className="h-3 w-1/2 rounded bg-fill-highlight-50 animate-pulse" />
                        </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        <div className="h-8 w-24 rounded bg-fill-highlight-50 animate-pulse" />
                        <div className="h-8 w-20 rounded bg-fill-highlight-50 animate-pulse" />
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] gap-5">
                <div className="min-w-0 flex flex-col gap-2.5">
                    <div className="h-4 w-28 rounded bg-fill-highlight-100 animate-pulse" />
                    <div className="h-3 w-full rounded bg-fill-highlight-50 animate-pulse" />
                    <div className="h-3 w-11/12 rounded bg-fill-highlight-50 animate-pulse" />
                    <div className="h-3 w-3/4 rounded bg-fill-highlight-50 animate-pulse" />
                </div>
                <div className="flex flex-col min-w-0 gap-5">
                    {Array.from({ length: 2 }).map((_, i) => (
                        <div key={i} className="flex flex-col gap-2.5">
                            <div className="h-4 w-24 rounded bg-fill-highlight-100 animate-pulse" />
                            <div className="h-16 w-full rounded border border-primary bg-surface-primary animate-pulse" />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

interface InboxDetailFrameProps {
    report: SignalReport
    /** Active inbox tab — drives the back link + copy-link target in the merged header. */
    tab: InboxTabKey
    /** Summary section heading icon + title. */
    summary: { icon: ReactNode; title: string }
    /** Extra primary action(s) rendered after the shared report actions. */
    primaryAction?: ReactNode
    /** Extra sections (Tasks, Reviewers) – defaults applied by callers. */
    children?: ReactNode
}

/**
 * Shared chrome for the Report and Pull request detail bodies. Owns the full page header
 * (back link, title, copy link) merged with the badges/meta/actions, then summary on the left
 * and supporting sections (Evidence, Runs, Reviewers) on the right. Mirrors desktop
 * `InboxDetailFrame`. AgentRunDetail keeps its own layout + shell header.
 */
export function InboxDetailFrame({
    report,
    tab,
    summary,
    primaryAction,
    children,
}: InboxDetailFrameProps): JSX.Element {
    const { reportSignals, reportSignalsLoading } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const signals = reportSignals ?? []
    const evidenceCount = reportSignals !== null ? signals.length : report.signal_count
    const hasEvidence = evidenceCount > 0

    const summaryPending =
        report.status === SignalReportStatus.IN_PROGRESS || report.status === SignalReportStatus.CANDIDATE

    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const displayTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    const reportPath = urls.inboxReport(tab, report.id)

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <div className="flex flex-col gap-3.5 mb-6 pb-5 border-b border-primary">
                <Link
                    to={urls.inbox(tab)}
                    className="inline-flex w-fit items-center gap-1.5 text-[12.5px] text-secondary hover:text-default no-underline"
                >
                    <IconArrowLeft className="text-sm" />
                    {INBOX_TAB_LABEL[tab]}
                </Link>
                <div className="flex items-start justify-between gap-4 flex-wrap">
                    {/* Priority square anchors the title; everything else collapses into the meta line. */}
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                        {report.priority && (
                            <div className="shrink-0 mt-0.5">
                                <SignalReportPriorityBadge
                                    priority={report.priority}
                                    explanation={report.priority_explanation}
                                />
                            </div>
                        )}
                        <div className="flex flex-col gap-2 min-w-0">
                            <h1 className="min-w-0 m-0 break-words text-xl font-bold leading-tight tracking-tight">
                                {conventionalTitle && (
                                    <ConventionalCommitScopeTag
                                        type={conventionalTitle.type}
                                        scope={conventionalTitle.scope}
                                    />
                                )}
                                {displayTitle}
                            </h1>
                            <ReportDetailMeta report={report} evidenceCount={evidenceCount} />
                        </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconLink />}
                            tooltip="Copy a link to this report"
                            onClick={() =>
                                void copyToClipboard(
                                    `${window.location.origin}${addProjectIdIfMissing(reportPath)}`,
                                    'report link'
                                )
                            }
                        >
                            Copy link
                        </LemonButton>
                        <ReportDetailActions report={report} />
                        {primaryAction}
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] gap-5">
                <div className="min-w-0">
                    <RightColumnSection icon={summary.icon} title={summary.title}>
                        {report.summary ? (
                            <LemonMarkdown className="text-sm text-secondary leading-normal break-words">
                                {report.summary}
                            </LemonMarkdown>
                        ) : (
                            <p className={`text-sm text-tertiary m-0${summaryPending ? ' italic' : ''}`}>
                                No summary yet – an agent is still investigating.
                            </p>
                        )}
                    </RightColumnSection>
                </div>

                <div className="flex flex-col min-w-0 gap-5">
                    {/* Pull request (when present) first, then reviewers, evidence, and runs. */}
                    {children}
                    <SuggestedReviewersSection report={report} />
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
                </div>
            </div>
        </div>
    )
}

/**
 * PR identity banner: the `repoSlug#number` ref, mono, with a PR glyph, linking out to GitHub.
 * Surfaced as the first right-column section when the report has a shipped implementation PR.
 */
function PullRequestBanner({ prUrl, prRef }: { prUrl: string; prRef: ParsedPrUrlParts }): JSX.Element {
    return (
        <Link
            to={prUrl}
            target="_blank"
            disableClientSideRouting
            className="group flex items-center gap-3 rounded border border-primary bg-surface-primary px-4 py-3 no-underline text-inherit transition-colors duration-150 hover:border-primary hover:bg-surface-secondary"
        >
            <span className="flex items-center justify-center size-7 shrink-0 rounded-full bg-success-highlight text-success">
                <IconPullRequest className="text-base" />
            </span>
            <span className="font-mono text-[13px] text-primary truncate">
                {prRef.repoSlug}#{prRef.number}
            </span>
            <Tooltip title="Open in GitHub">
                <span className="shrink-0 text-tertiary transition-colors group-hover:text-default">
                    <IconExternal className="text-base" />
                </span>
            </Tooltip>
        </Link>
    )
}

/**
 * Unified report detail for Pull requests / Reports / Not actionable. The PR banner +
 * "Open in GitHub" action surface only when the report has a shipped implementation PR;
 * otherwise it reads as a plain report. Runs keep their own `AgentRunDetail`.
 */
export function ReportDetail({ report, tab }: { report: SignalReport; tab: InboxTabKey }): JSX.Element {
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const prRef = prUrl ? parsePrUrlParts(prUrl) : null
    const hasPr = !!(prRef && prUrl)

    return (
        <InboxDetailFrame
            report={report}
            tab={tab}
            summary={{ icon: hasPr ? <IconPullRequest /> : <IconDocument />, title: 'Summary' }}
            primaryAction={
                hasPr ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        sideIcon={<IconExternal />}
                        to={prUrl}
                        targetBlank
                        tooltip={`${prRef.repoSlug}#${prRef.number}`}
                    >
                        Open in GitHub
                    </LemonButton>
                ) : undefined
            }
        >
            {hasPr ? (
                <RightColumnSection icon={<IconCode />} title="Diff">
                    <PullRequestBanner prUrl={prUrl} prRef={prRef} />
                </RightColumnSection>
            ) : null}
        </InboxDetailFrame>
    )
}
