import clsx from 'clsx'
import { router } from 'kea-router'

import { IconArchive, IconPullRequest, IconUndo } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { scoutDisplayName } from 'lib/signals/signalCardSourceLine'
import { urls } from 'scenes/urls'

import { InboxFlatListTabKey, SignalReport, SignalReportStatus, SignalSourceProduct } from '../../types'
import { dismissalReasonLabel, DismissalReasonValue } from '../../utils/dismissalReasons'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
    parseConventionalCommitTitle,
    parsePrUrlParts,
    safeHttpUrl,
} from '../../utils/reportPresentation'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportBillingBadge } from '../badges/SignalReportBillingBadge'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import {
    hasKnownSourceProduct,
    knownSourceProductEntries,
    SourceProductIconRow,
    sourceProductsTooltipTitle,
} from '../badges/sourceProductIcons'
import { inboxCardRowClassName, useReportArchive } from './useReportArchive'

// ── Shared card sub-components ────────────────────────────────────────────────

export function ConventionalCommitScopeTag({ type, scope }: { type: string; scope: string | null }): JSX.Element {
    const label = scope ? `${type}(${scope})` : type
    // Rendered as an inline prefix to the title text (not a flex sibling), so it stays on the
    // title's first line and the title wraps beneath it. `align-middle` keeps it centered on that
    // line; `font-normal` stops it inheriting the title's weight.
    return (
        <LemonTag size="small" className="mr-1 align-middle font-mono font-normal select-none" title={label}>
            {label}
        </LemonTag>
    )
}

/** Icon stack + primary source-product label, with a `+ n` tail when more sources contributed. */
export function InboxCardSourceMeta({
    sourceProducts,
    scoutName,
}: {
    sourceProducts?: string[] | null
    /** Authoring scout's display name, when scout-authored — appended to the "Scout" label. */
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
            <div className="flex items-center gap-2 min-w-0 text-xs text-tertiary leading-none select-none cursor-help">
                <SourceProductIconRow entries={entries} className="flex items-center gap-1.5 shrink-0" />
                <span>
                    {primaryLabel}
                    {overflow.length > 0 ? ` + ${overflow.length}` : null}
                </span>
            </div>
        </Tooltip>
    )
}

// ── PR status badge ─────────────────────────────────────────────────────────

/**
 * PR open/merged/closed state, mapped to muted palette tags (outlined: --success / --purple /
 * --danger). We have no real PR status from GitHub on the report, so it's inferred from the
 * report status: a resolved report means its implementation PR merged (webhook-driven on merge),
 * a failed one means the PR never landed, everything else is still an open PR.
 */
const PR_BADGE_STATE: Record<'open' | 'merged' | 'closed', { label: string; type: LemonTagType }> = {
    open: { label: 'open', type: 'success' },
    merged: { label: 'merged', type: 'completion' },
    closed: { label: 'closed', type: 'danger' },
}

type PrBadgeState = keyof typeof PR_BADGE_STATE

function derivePrState(status: SignalReportStatus): PrBadgeState {
    if (status === SignalReportStatus.RESOLVED) {
        return 'merged'
    }
    if (status === SignalReportStatus.FAILED) {
        return 'closed'
    }
    return 'open'
}

/**
 * PR status badge for the card's top-right corner: a state-colored tag with the pull-request
 * icon and `#1234`. When a PR URL is known the whole badge is the GitHub link itself.
 */
function PrBadge({
    prNumber,
    prUrl,
    state,
}: {
    prNumber: string
    prUrl?: string | null
    state: PrBadgeState
}): JSX.Element {
    const { label, type } = PR_BADGE_STATE[state]
    const badge = (
        <LemonTag type={type} size="small" icon={<IconPullRequest />} className="font-mono tabular-nums">
            #{prNumber}
        </LemonTag>
    )

    if (!prUrl) {
        return <Tooltip title={`Pull request #${prNumber} (${label})`}>{badge}</Tooltip>
    }

    return (
        <Tooltip title={`Open pull request #${prNumber} (${label}) on GitHub`}>
            <Link
                to={prUrl}
                target="_blank"
                disableClientSideRouting
                onClick={(e) => e.stopPropagation()}
                aria-label={`Open pull request #${prNumber} (${label}) on GitHub`}
            >
                {badge}
            </Link>
        </Tooltip>
    )
}

// ── ReportCard ────────────────────────────────────────────────────────────────

/**
 * Unified inbox list card for reports and pull requests. The presence of a parseable
 * implementation PR (`hasPr`) drives the divergences: PR cards get a solid border, a
 * `#1234` state badge, the repo slug in the meta row, and no status/actionability chips;
 * plain reports get a dashed border, a summary placeholder, and the status/actionability chips.
 */
export function ReportCard({
    report,
    tabKey = 'reports',
    attached = false,
    onArchive,
    onRestore,
}: {
    report: SignalReport
    tabKey?: InboxFlatListTabKey
    attached?: boolean
    onArchive?: (reason: DismissalReasonValue, note: string) => void
    onRestore?: () => void
}): JSX.Element {
    const isArchived = tabKey === 'archived'
    // Resolved reports are terminal (their implementation PR merged) – shown for reference in the
    // Archive tab. They can't be restored or re-archived; refunding their PR lives in the detail pane.
    const isResolved = report.status === SignalReportStatus.RESOLVED
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const prUrlParts = prUrl ? parsePrUrlParts(prUrl) : null
    const hasPr = prUrlParts != null
    const prNumber = prUrlParts?.number ?? null
    const repoSlug = prUrlParts?.repoSlug ?? null

    const hasSource = hasKnownSourceProduct(report.source_products)
    const isReady = report.status === 'ready'
    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const cardTitle = displayConventionalCommitTitle(report.title, hasPr ? 'Untitled pull request' : 'Untitled report')
    const headline = deriveHeadline(report.summary)
    const detailUrl = urls.inboxReport(tabKey, report.id)

    const { isArchiving, onArchiveClick } = useReportArchive({
        reportId: report.id,
        cardTitle,
        report,
        surface: 'list_row',
        onArchive,
    })

    const isRefunded = !!report.refund

    // On the Archive tab, surface why it was dismissed (reason tag + note tooltip) when we have it.
    // Key off the report still being suppressed, not the tab: a report that was dismissed, restored,
    // then resolved keeps its old dismissal artefact, and showing that tag would mislabel finished work.
    // The dedicated billing badge already marks refunded reports, so skip the duplicate chip there.
    const dismissalLabel =
        isArchived && report.status === SignalReportStatus.SUPPRESSED && !isRefunded
            ? dismissalReasonLabel(report.dismissal_reason)
            : null

    // Permanent billing marker (Refunded / Free) — shown on both PR cards and plain reports.
    const showBillingBadge = isRefunded || !!report.billing_exempt_reason

    // PR cards show repo · source; reports show source · status · actionability.
    const showMeta = hasPr
        ? repoSlug != null || hasSource || showBillingBadge
        : hasSource ||
          !isReady ||
          report.actionability != null ||
          report.is_suggested_reviewer === true ||
          !!dismissalLabel ||
          showBillingBadge

    return (
        <div className={clsx('relative', inboxCardRowClassName(attached, { dashed: !hasPr }))}>
            {hasPr && prNumber != null ? (
                <div className="absolute right-4 top-3 z-10">
                    <PrBadge prNumber={prNumber} prUrl={prUrl} state={derivePrState(report.status)} />
                </div>
            ) : null}

            <Link to={detailUrl} className="flex min-w-0 flex-1 items-start gap-3 text-left text-inherit no-underline">
                {report.priority && (
                    <div className="shrink-0">
                        <SignalReportPriorityBadge priority={report.priority} />
                    </div>
                )}

                <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                    {/* Pad clear of the absolute PR badge on mobile, where the title spans the full card width. */}
                    <div
                        className={clsx(
                            'min-w-0 break-words font-semibold text-sm leading-snug text-balance',
                            hasPr && 'pr-14 @lg:pr-0'
                        )}
                    >
                        {conventionalTitle && (
                            <ConventionalCommitScopeTag type={conventionalTitle.type} scope={conventionalTitle.scope} />
                        )}
                        {cardTitle}
                    </div>

                    {headline ? (
                        <p
                            className={clsx(
                                'min-w-0',
                                !hasPr && !isReady && 'opacity-80',
                                'break-words line-clamp-2 text-xs text-secondary leading-snug m-0'
                            )}
                        >
                            {headline}
                        </p>
                    ) : !hasPr ? (
                        <p
                            className={clsx(
                                'min-w-0',
                                !isReady && 'opacity-80',
                                'break-words line-clamp-2 text-xs text-tertiary italic leading-snug m-0'
                            )}
                        >
                            No summary yet – still collecting context.
                        </p>
                    ) : null}

                    {showMeta ? (
                        <div className="flex items-center flex-wrap mt-1.5 min-w-0 gap-2.5 text-xs text-tertiary leading-none select-none">
                            {hasPr && repoSlug ? <span className="truncate font-mono">{repoSlug}</span> : null}
                            <InboxCardSourceMeta
                                sourceProducts={report.source_products}
                                scoutName={scoutDisplayName(report.scout_name)}
                            />
                            {!hasPr && (!isReady || !report.actionability) && (
                                <SignalReportStatusBadge status={report.status} />
                            )}
                            {!hasPr && report.actionability && (
                                <SignalReportActionabilityBadge actionability={report.actionability} />
                            )}
                            {dismissalLabel && (
                                <Tooltip title={report.dismissal_note || undefined}>
                                    <LemonTag size="small" icon={<IconArchive />}>
                                        {dismissalLabel}
                                    </LemonTag>
                                </Tooltip>
                            )}
                            <SignalReportBillingBadge report={report} />
                        </div>
                    ) : null}

                    {/* In flow on mobile (the card stacks); pinned to the card's bottom-right corner on desktop. */}
                    <div className="mt-0.5 @lg:absolute @lg:right-4 @lg:bottom-3 @lg:z-10 @lg:mt-0">
                        <TZLabel
                            time={report.updated_at ?? report.created_at}
                            className="text-xs text-tertiary tabular-nums"
                            title="Last updated"
                        />
                    </div>
                </div>
            </Link>

            {/* Refund deliberately isn't offered at the card level – it lives in the report detail
                pane, where the consequences are in view. Resolved reports are terminal and a refunded
                archived report can't be restored, so neither carries actions – skip the column (and
                divider) for both. */}
            {!isResolved && !(isArchived && isRefunded) && (
                <div className="flex items-center justify-end gap-2.5 shrink-0 @lg:self-stretch @lg:border-l @lg:border-primary @lg:pl-3">
                    {isArchived ? (
                        // A refunded report can't be restored (its PR can never be billed again).
                        !isRefunded && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconUndo />}
                                tooltip="Restore this report to the inbox"
                                aria-label="Restore this report to the inbox"
                                onClick={(event) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    onRestore?.()
                                }}
                            >
                                Restore
                            </LemonButton>
                        )
                    ) : (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconArchive />}
                                tooltip="Archive this report"
                                aria-label="Archive this report"
                                loading={isArchiving}
                                onClick={onArchiveClick}
                            >
                                Archive
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                tooltip="Open the full report – summary, evidence, and actions"
                                onClick={(event) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    router.actions.push(detailUrl)
                                }}
                            >
                                Review
                            </LemonButton>
                        </>
                    )}
                </div>
            )}
        </div>
    )
}
