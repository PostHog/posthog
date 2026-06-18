import clsx from 'clsx'
import { router } from 'kea-router'

import { IconArchive, IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { InboxFlatListTabKey, SignalReport, SignalReportStatus } from '../../types'
import { DismissalReasonValue } from '../../utils/dismissalReasons'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
    parseConventionalCommitTitle,
    parsePrUrlParts,
    safeHttpUrl,
} from '../../utils/reportPresentation'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import { hasKnownSourceProduct, knownSourceProductEntries, SourceProductIconRow } from '../badges/sourceProductIcons'
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
export function InboxCardSourceMeta({ sourceProducts }: { sourceProducts?: string[] | null }): JSX.Element | null {
    const [primary, ...overflow] = knownSourceProductEntries(sourceProducts)
    if (!primary) {
        return null
    }
    return (
        <div className="flex items-center gap-2 min-w-0 text-xs text-tertiary leading-none select-none">
            <SourceProductIconRow entries={[primary, ...overflow]} className="flex items-center gap-1.5 shrink-0" />
            <span>
                {primary.meta.label}
                {overflow.length > 0 ? ` + ${overflow.length}` : null}
            </span>
        </div>
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
}: {
    report: SignalReport
    tabKey?: InboxFlatListTabKey
    attached?: boolean
    onArchive?: (reason: DismissalReasonValue, note: string) => void
}): JSX.Element {
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

    const { isArchiving, onArchiveClick } = useReportArchive({ reportId: report.id, cardTitle, onArchive })

    // PR cards show repo · source; reports show source · status · actionability.
    const showMeta = hasPr
        ? repoSlug != null || hasSource
        : hasSource || !isReady || report.actionability != null || report.is_suggested_reviewer === true

    return (
        <div className={clsx('relative', inboxCardRowClassName(attached, { dashed: !hasPr }))}>
            {hasPr && prNumber != null ? (
                <div className="absolute right-4 top-3 z-10">
                    <PrBadge prNumber={prNumber} prUrl={prUrl} state={derivePrState(report.status)} />
                </div>
            ) : null}

            <div className="absolute right-4 bottom-3 z-10">
                <TZLabel
                    time={report.updated_at ?? report.created_at}
                    className="text-xs text-tertiary tabular-nums"
                    title="Last updated"
                />
            </div>

            <Link to={detailUrl} className="flex min-w-0 flex-1 items-start gap-3 text-left text-inherit no-underline">
                {report.priority && (
                    <div className="shrink-0">
                        <SignalReportPriorityBadge priority={report.priority} />
                    </div>
                )}

                <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                    <div className="min-w-0 break-words font-semibold text-sm leading-snug">
                        {conventionalTitle && (
                            <ConventionalCommitScopeTag type={conventionalTitle.type} scope={conventionalTitle.scope} />
                        )}
                        {cardTitle}
                    </div>

                    {headline ? (
                        <div className={clsx('mt-0.5 min-w-0', !hasPr && !isReady && 'opacity-80')}>
                            <p className="break-words line-clamp-2 text-xs text-secondary leading-snug m-0">
                                {headline}
                            </p>
                        </div>
                    ) : !hasPr ? (
                        <div className={clsx('mt-0.5 min-w-0', !isReady && 'opacity-80')}>
                            <p className="break-words line-clamp-2 text-xs text-tertiary italic leading-snug m-0">
                                No summary yet – still collecting context.
                            </p>
                        </div>
                    ) : null}

                    {showMeta ? (
                        <div className="flex items-center flex-wrap mt-1.5 min-w-0 gap-2.5 text-xs text-tertiary leading-none select-none">
                            {hasPr && repoSlug ? <span className="truncate font-mono">{repoSlug}</span> : null}
                            <InboxCardSourceMeta sourceProducts={report.source_products} />
                            {!hasPr && (!isReady || !report.actionability) && (
                                <SignalReportStatusBadge status={report.status} />
                            )}
                            {!hasPr && report.actionability && (
                                <SignalReportActionabilityBadge actionability={report.actionability} />
                            )}
                        </div>
                    ) : null}
                </div>
            </Link>

            <div className="flex items-center gap-2.5 self-stretch shrink-0 border-l border-primary pl-3">
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
                    onClick={(event) => {
                        event.preventDefault()
                        event.stopPropagation()
                        router.actions.push(detailUrl)
                    }}
                >
                    Review
                </LemonButton>
            </div>
        </div>
    )
}
