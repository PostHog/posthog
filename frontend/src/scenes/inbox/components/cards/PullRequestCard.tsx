import { IconPullRequest } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

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

export function PullRequestCard({ report }: { report: SignalReport }): JSX.Element {
    const prRepoSlug = report.implementation_pr_url ? parsePrRepoSlug(report.implementation_pr_url) : null
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
                            {prRepoSlug ? <span>{prRepoSlug}</span> : null}
                            {prRepoSlug && hasSource ? <span aria-hidden>·</span> : null}
                            <InboxCardSourceMeta sourceProducts={report.source_products} />
                        </div>
                    )}
                </div>
            </div>

            <div className="flex items-center gap-2.5 self-stretch shrink-0 border-l border-primary pl-3">
                <span className="flex items-center gap-1 text-xs text-tertiary">
                    <IconPullRequest className="text-sm" />
                </span>
                <span className="rounded bg-fill-primary px-2 py-1 text-xs font-medium text-default group-hover:bg-fill-primary-hover">
                    Review
                </span>
            </div>
        </Link>
    )
}
