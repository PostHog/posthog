import { useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { IconArrowLeft, IconDocument, IconEllipsis, IconExternal, IconPullRequest, IconSearch } from '@posthog/icons'
import { LemonButton, LemonTabs, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { scoutDisplayName } from 'lib/signals/signalCardSourceLine'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { InboxTabKey, INBOX_TAB_LABEL, SignalReport, SignalReportStatus, SignalSourceProduct } from '../../types'
import {
    displayConventionalCommitTitle,
    parseConventionalCommitTitle,
    parsePrUrlParts,
    safeHttpUrl,
} from '../../utils/reportPresentation'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import {
    hasKnownSourceProduct,
    knownSourceProductEntries,
    SourceProductIconRow,
    sourceProductsTooltipTitle,
} from '../badges/sourceProductIcons'
import { ConventionalCommitScopeTag } from '../cards/ReportCard'
import { CommitContent } from './artefactTypes'
import { DetailSection } from './DetailSection'
import { PullRequestBranchTag, PullRequestDiffPanel } from './PullRequestDiffPanel'
import { PullRequestReviewCommentsSection } from './PullRequestReviewCommentsSection'
import { ReportActivitySection } from './ReportActivitySection'
import { ReportDetailAction, useReportDetailActions } from './ReportDetailActions'
import { ReportTasksSection } from './ReportTasksSection'
import { SuggestedReviewersSection } from './SuggestedReviewersSection'

/**
 * Status / priority / actionability badges for a report's detail header. Mirrors desktop `InboxDetailFrame`.
 * The judgment rationale (when present) is sourced from the detail logic's loaded artefacts and surfaced by
 * a circled help icon overlaying the chip's top-right corner; the chip is then hoverable for the rationale.
 */
export function ReportDetailBadges({
    report,
    priorityExplanation,
    actionabilityExplanation,
}: {
    report: SignalReport
    priorityExplanation?: string | null
    actionabilityExplanation?: string | null
}): JSX.Element {
    return (
        <>
            <SignalReportPriorityBadge priority={report.priority} explanation={priorityExplanation} />
            {/* "Ready" is the default terminal state; once actionability is known, surface that instead. */}
            {(report.status !== 'ready' || !report.actionability) && <SignalReportStatusBadge status={report.status} />}
            <SignalReportActionabilityBadge
                actionability={report.actionability}
                explanation={actionabilityExplanation}
            />
        </>
    )
}

/** Shared explainer for the finding count in the meta line and the Evidence section. */
const FINDINGS_TOOLTIP =
    'Findings are the individual pieces of evidence – signals from your connected sources and scouts – that were grouped into this report.'

/**
 * Single meta line under the title: status/actionability chips, then dot-separated stats
 * (finding count · updated · source stack). `evidenceCount` switches to the live signal count once
 * findings load, so the row reads the same before and after the query resolves.
 */
function ReportDetailMeta({
    report,
    evidenceCount,
    actionabilityExplanation,
    scoutName,
}: {
    report: SignalReport
    evidenceCount: number
    actionabilityExplanation?: string | null
    /** Authoring scout's display name, when the report was scout-authored — appended to the "Scout" chip. */
    scoutName?: string | null
}): JSX.Element {
    const hasSource = hasKnownSourceProduct(report.source_products)
    // "Ready" is the default terminal state; surface the status chip only until actionability is known.
    const showStatus = report.status !== 'ready' || !report.actionability

    const stats: ReactNode[] = []
    if (evidenceCount > 0) {
        stats.push(
            <Tooltip title={FINDINGS_TOOLTIP}>
                <span className="tabular-nums cursor-help">
                    {evidenceCount} finding{evidenceCount === 1 ? '' : 's'}
                </span>
            </Tooltip>
        )
    }
    // Mirrors error tracking's "First seen" / "Last seen": surface both lifecycle moments as distinct facts.
    stats.push(
        <span className="flex items-center gap-1">
            <span>First seen</span>
            <TZLabel time={report.created_at} />
        </span>
    )
    stats.push(
        <span className="flex items-center gap-1">
            <span>Last updated</span>
            <TZLabel time={report.updated_at ?? report.created_at} />
        </span>
    )
    if (hasSource) {
        stats.push(<MetaSourceStack sourceProducts={report.source_products} scoutName={scoutName} />)
    }

    return (
        <div className="flex items-center gap-x-2 gap-y-1.5 flex-wrap text-xs text-tertiary leading-none select-none">
            {showStatus && <SignalReportStatusBadge status={report.status} />}
            <SignalReportActionabilityBadge
                actionability={report.actionability}
                explanation={actionabilityExplanation}
            />
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

/** Source-product icon stack reused inside the detail meta row. */
function MetaSourceStack({
    sourceProducts,
    scoutName,
}: {
    sourceProducts?: string[] | null
    scoutName?: string | null
}): JSX.Element | null {
    const entries = knownSourceProductEntries(sourceProducts)
    const [primary, ...overflow] = entries
    if (!primary) {
        return null
    }
    // Name the authoring scout on a scout-authored report so it's clear at a glance who wrote it.
    const primaryLabel =
        primary.key === SignalSourceProduct.SignalsScout && scoutName
            ? `${primary.meta.label} · ${scoutName}`
            : primary.meta.label
    return (
        <Tooltip title={sourceProductsTooltipTitle(entries)}>
            <span className="inline-flex items-center gap-1.5 min-w-0 cursor-help">
                <SourceProductIconRow entries={entries} className="inline-flex items-center gap-1 shrink-0" />
                <span>
                    {primaryLabel}
                    {overflow.length > 0 ? ` + ${overflow.length}` : null}
                </span>
            </span>
        </Tooltip>
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
                <div className="flex flex-col gap-3 @2xl:flex-row @2xl:items-start @2xl:justify-between @2xl:gap-4">
                    <div className="flex items-start gap-3 min-w-0 @2xl:flex-1">
                        <div className="size-7 shrink-0 mt-0.5 rounded bg-fill-highlight-100 animate-pulse" />
                        <div className="flex flex-col gap-2 min-w-0 flex-1">
                            <div className="h-6 w-2/3 rounded bg-fill-highlight-100 animate-pulse" />
                            <div className="h-3 w-1/2 rounded bg-fill-highlight-50 animate-pulse" />
                        </div>
                    </div>
                    <div className="flex items-center flex-wrap gap-2 @2xl:shrink-0">
                        <div className="h-8 w-24 rounded bg-fill-highlight-50 animate-pulse" />
                        <div className="h-8 w-20 rounded bg-fill-highlight-50 animate-pulse" />
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 @5xl:grid-cols-[minmax(0,80ch)_minmax(22rem,1fr)] gap-5">
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
    /** Active inbox tab — drives the copy-link target in the merged header. */
    tab: InboxTabKey
    /** Summary section heading icon + title. */
    summary: { icon: ReactNode; title: string }
    /** Extra primary action(s) rendered after the shared report actions. */
    primaryAction?: ReactNode
    /** Diff body. When present, the overview and this render behind two tabs (GitHub-style PR view). */
    diffSection?: ReactNode
    /** Branch tag shown in the "Files changed" tab label, so the tab signals there's code behind it. */
    diffBranchTag?: ReactNode
    /** Extra sections (Tasks, Reviewers) – defaults applied by callers. */
    children?: ReactNode
}

/**
 * Shared chrome for the Report and Pull request detail bodies. Owns the full page header
 * (title, copy link) merged with the badges/meta/actions, then summary on the left
 * and supporting sections (Evidence, Runs, Reviewers) on the right. Mirrors desktop
 * `InboxDetailFrame`. AgentRunDetail keeps its own layout + shell header.
 */
export function InboxDetailFrame({
    report,
    tab,
    summary,
    primaryAction,
    diffSection,
    diffBranchTag,
    children,
}: InboxDetailFrameProps): JSX.Element {
    const { reportSignals, reportSignalsLoading, priorityExplanation, actionabilityExplanation } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    // GitHub-style PR view: when a diff is present, the overview and the diff live behind two tabs.
    const [activeDetailTab, setActiveDetailTab] = useState<'overview' | 'files'>('overview')
    const hasDiff = !!diffSection
    const signals = reportSignals ?? []
    const evidenceCount = reportSignals !== null ? signals.length : report.signal_count
    const hasEvidence = evidenceCount > 0

    // Which scout authored this report — the serializer resolves the skill_name off the backing signals.
    const scoutName = scoutDisplayName(report.scout_name)

    const summaryPending =
        report.status === SignalReportStatus.IN_PROGRESS || report.status === SignalReportStatus.CANDIDATE

    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const displayTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    const reportPath = urls.inboxReport(tab, report.id)

    // Secondary actions as data so the same set renders inline as buttons on wide layouts and as a
    // standard `LemonMenu` on narrow ones; the primary action stays inline either way.
    const detailActions = useReportDetailActions(report)
    const reportActions: ReportDetailAction[] = [
        {
            key: 'copy-link',
            label: 'Copy link',
            icon: <IconLink />,
            tooltip: 'Copy a link to this report',
            onClick: () =>
                void copyToClipboard(`${window.location.origin}${addProjectIdIfMissing(reportPath)}`, 'report link'),
        },
        ...detailActions,
    ]
    const overflowMenuItems: LemonMenuItem[] = reportActions.map((action) => ({
        label: action.label,
        icon: action.icon,
        disabledReason: action.loading ? 'Working…' : undefined,
        onClick: action.onClick,
    }))

    const overviewBody = (
        <div className="grid grid-cols-1 @5xl:grid-cols-[minmax(0,80ch)_minmax(22rem,1fr)] gap-5">
            <div className="min-w-0">
                <DetailSection icon={summary.icon} title={summary.title}>
                    {report.summary ? (
                        <LemonMarkdown
                            className="text-sm text-secondary leading-relaxed break-words [&>*+*]:mt-3 [&_li]:my-1 [&_ul]:my-2 [&_ol]:my-2 [&_h1]:mt-5 [&_h2]:mt-5 [&_h3]:mt-4"
                            disableImages
                        >
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
                {/* Pull request (when present) first, then reviewers, evidence, runs, and activity. */}
                {children}
                <SuggestedReviewersSection report={report} />
                {hasEvidence && (
                    <DetailSection
                        icon={<IconSearch />}
                        title="Evidence"
                        rightSlot={
                            <Tooltip title={FINDINGS_TOOLTIP}>
                                <span className="text-[0.6875rem] text-tertiary tabular-nums cursor-help">
                                    {evidenceCount} finding{evidenceCount === 1 ? '' : 's'}
                                </span>
                            </Tooltip>
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
                    </DetailSection>
                )}
                <ReportTasksSection report={report} />
                <ReportActivitySection report={report} />
            </div>
        </div>
    )

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            {/* With a diff present the tab bar owns the full-width divider, so the heading drops its own. */}
            <div className={`flex flex-col gap-3.5 ${hasDiff ? 'mb-4' : 'mb-6 pb-5 border-b border-primary'}`}>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    to={urls.inbox(tab)}
                    className="-ml-2 w-fit"
                >
                    {INBOX_TAB_LABEL[tab]}
                </LemonButton>
                <div className="flex flex-col gap-3 @2xl:flex-row @2xl:items-start @2xl:justify-between @2xl:gap-4">
                    {/* Priority square anchors the title; everything else collapses into the meta line. */}
                    <div className="flex items-start gap-3 min-w-0 @2xl:flex-1">
                        {report.priority && (
                            <div className="shrink-0 mt-0.5">
                                <SignalReportPriorityBadge
                                    priority={report.priority}
                                    explanation={priorityExplanation}
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
                            <ReportDetailMeta
                                report={report}
                                evidenceCount={evidenceCount}
                                actionabilityExplanation={actionabilityExplanation}
                                scoutName={scoutName}
                            />
                        </div>
                    </div>
                    <div className="flex items-center gap-2 @2xl:shrink-0">
                        {primaryAction}
                        {/* Buttons inline on wide layouts; collapse into a standard LemonMenu kebab below @4xl. */}
                        <div className="hidden @4xl:flex items-center gap-2">
                            {reportActions.map((action) => (
                                <LemonButton
                                    key={action.key}
                                    type="secondary"
                                    size="small"
                                    icon={action.icon}
                                    loading={action.loading}
                                    tooltip={action.tooltip}
                                    onClick={action.onClick}
                                >
                                    {action.label}
                                </LemonButton>
                            ))}
                        </div>
                        <LemonMenu items={overflowMenuItems} placement="bottom-end">
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconEllipsis />}
                                aria-label="More actions"
                                className="@4xl:hidden"
                            />
                        </LemonMenu>
                    </div>
                </div>
            </div>

            {hasDiff ? (
                <LemonTabs
                    activeKey={activeDetailTab}
                    onChange={setActiveDetailTab}
                    tabs={[
                        { key: 'overview', label: 'Overview', content: overviewBody },
                        {
                            key: 'files',
                            label: (
                                <span className="flex items-center gap-1.5">
                                    <span>Files changed</span>
                                    {diffBranchTag}
                                </span>
                            ),
                            content: <>{diffSection}</>,
                        },
                    ]}
                />
            ) : (
                overviewBody
            )}
        </div>
    )
}

/** Point a PR URL at its diff/files tab, without double-appending if it's already there. */
function prFilesUrl(prUrl: string): string {
    return prUrl.replace(/\/+$/, '').replace(/(\/files)?$/, '/files')
}

/**
 * Unified report detail for Pull requests / Reports / Not actionable. The "Open in GitHub" action
 * surfaces only when the report has a shipped implementation PR; otherwise it reads as a plain
 * report. When the report has a "Commit pushed" artefact, a GitHub-style "Files changed" tab renders
 * the branch's diff against the default branch alongside the overview. Runs keep their own `AgentRunDetail`.
 */
export function ReportDetail({ report, tab }: { report: SignalReport; tab: InboxTabKey }): JSX.Element {
    const { latestCommitArtefact } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))

    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const prRef = prUrl ? parsePrUrlParts(prUrl) : null
    const hasPr = !!(prRef && prUrl)

    // The report's branch to diff comes from the latest "Commit pushed" artefact; only offer the diff
    // tab when that artefact carries the repo + branch the diff endpoint needs.
    const commit = latestCommitArtefact ? (latestCommitArtefact.content as CommitContent) : null
    const canDiff = !!(commit?.repository && commit?.branch)

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
                        to={prFilesUrl(prUrl)}
                        targetBlank
                        tooltip={`${prRef.repoSlug}#${prRef.number}`}
                    >
                        Open in GitHub
                    </LemonButton>
                ) : undefined
            }
            diffSection={
                canDiff && commit && latestCommitArtefact ? (
                    <>
                        <PullRequestDiffPanel report={report} commit={commit} />
                        {/* Review conversation only exists once a PR is shipped for this report. */}
                        {report.implementation_pr_url && (
                            <PullRequestReviewCommentsSection report={report} commit={commit} />
                        )}
                    </>
                ) : undefined
            }
            diffBranchTag={
                canDiff && commit && latestCommitArtefact ? <PullRequestBranchTag commit={commit} /> : undefined
            }
        />
    )
}
