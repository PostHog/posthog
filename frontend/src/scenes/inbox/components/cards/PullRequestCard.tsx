import { IconExternal, IconPullRequest } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SignalReport } from '../../types'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
    parseConventionalCommitTitle,
    parsePrRepoSlug,
} from '../../utils/reportPresentation'
import { hasKnownSourceProduct } from '../badges/sourceProductIcons'
import { ConventionalCommitScopeTag, InboxCardSourceMeta, PriorityMonogram } from './ReportCard'

/** Pull the `#1234` PR number out of a GitHub PR URL, mirroring `parsePrRepoSlug`. */
function parsePrNumber(prUrl: string): number | null {
    try {
        const url = new URL(prUrl)
        const match = url.pathname.match(/\/pull\/(\d+)(?:$|[/?#])/)
        if (!match) {
            return null
        }
        const value = Number.parseInt(match[1], 10)
        return Number.isFinite(value) ? value : null
    } catch {
        return null
    }
}

/**
 * PR marker rendered in the card's right rail, styled like desktop's `PrDiffIndicator`
 * (mono, tabular nums, shrink-0). Desktop fetches live diff stats (`+12 −3 · 4 files`)
 * via a git hook; PostHog Cloud has no such data source on the report, so we render a
 * faithful `#1234` PR marker in the same visual slot instead of fabricating diff counts.
 */
function PrMarker({ prNumber }: { prNumber: number }): JSX.Element {
    return (
        <Tooltip title={`Pull request #${prNumber}`}>
            <span className="flex shrink-0 items-center gap-1 font-mono text-[12px] text-tertiary tabular-nums cursor-help select-none">
                <IconPullRequest className="text-sm text-secondary" />#{prNumber}
            </span>
        </Tooltip>
    )
}

export function PullRequestCard({ report }: { report: SignalReport }): JSX.Element {
    const prUrl = report.implementation_pr_url ?? null
    const prRepoSlug = prUrl ? parsePrRepoSlug(prUrl) : null
    const prNumber = prUrl ? parsePrNumber(prUrl) : null
    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const cardTitle = displayConventionalCommitTitle(report.title, 'Untitled pull request')
    const headline = deriveHeadline(report.summary)
    const hasSource = hasKnownSourceProduct(report.source_products)

    return (
        <Link
            to={urls.inboxReport('pulls', report.id)}
            className="group flex w-full items-start gap-3 rounded border border-primary bg-surface-primary px-4 py-3.5 text-left text-inherit no-underline transition-colors duration-150 hover:border-primary hover:bg-surface-secondary"
        >
            <div className="flex min-w-0 flex-1 items-start gap-3">
                <PriorityMonogram priority={report.priority} />

                <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                    <div className="flex items-center gap-1 flex-wrap min-w-0">
                        {conventionalTitle && (
                            <ConventionalCommitScopeTag type={conventionalTitle.type} scope={conventionalTitle.scope} />
                        )}
                        <span className="min-w-0 flex-1 break-words font-semibold text-sm leading-snug">
                            {cardTitle}
                        </span>
                    </div>

                    {headline ? (
                        <p className="break-words mt-0.5 line-clamp-2 text-xs text-secondary leading-snug m-0">
                            {headline}
                        </p>
                    ) : null}

                    {(prRepoSlug || hasSource) && (
                        <div className="flex items-center gap-2 mt-1.5 min-w-0 text-xs text-tertiary leading-none select-none">
                            {prRepoSlug ? <span className="truncate font-mono">{prRepoSlug}</span> : null}
                            {prRepoSlug && hasSource ? <span aria-hidden>·</span> : null}
                            <InboxCardSourceMeta sourceProducts={report.source_products} />
                        </div>
                    )}
                </div>
            </div>

            <div className="flex items-center gap-2.5 self-stretch shrink-0 border-l border-primary pl-3">
                {prNumber != null ? (
                    <PrMarker prNumber={prNumber} />
                ) : (
                    <span className="flex shrink-0 items-center text-xs text-tertiary">
                        <IconPullRequest className="text-sm" />
                    </span>
                )}

                {prUrl ? (
                    <Tooltip title="Open in GitHub">
                        <Link
                            to={prUrl}
                            target="_blank"
                            disableClientSideRouting
                            onClick={(e) => e.stopPropagation()}
                            className="flex shrink-0 items-center justify-center rounded p-1 text-tertiary transition-colors hover:bg-fill-primary hover:text-default"
                            aria-label="Open in GitHub"
                        >
                            <IconExternal className="text-sm" />
                        </Link>
                    </Tooltip>
                ) : null}

                <span className="rounded bg-fill-primary px-2 py-1 text-xs font-medium text-default group-hover:bg-fill-primary-hover">
                    Review
                </span>
            </div>
        </Link>
    )
}
