import { IconExternal, IconPullRequest } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { SignalReport } from '../../types'
import { InboxDetailFrame } from './ReportDetail'

interface ParsedPrUrl {
    owner: string
    repo: string
    number: string
    repoSlug: string
}

/** Parse a canonical GitHub PR URL into its parts. Mirrors desktop `parsePrUrl`. */
function parsePrUrl(prUrl: string): ParsedPrUrl | null {
    try {
        const url = new URL(prUrl)
        const match = url.pathname.match(/^\/([^/]+)\/([^/]+)\/pull\/(\d+)(?:$|[/?#])/)
        if (!match) {
            return null
        }
        const [, owner, repo, number] = match
        return { owner, repo, number, repoSlug: `${owner}/${repo}` }
    } catch {
        return null
    }
}

/**
 * PR identity banner: the `repoSlug#number` ref, mono, with a PR glyph, linking out to GitHub.
 * Mirrors desktop's PR breadcrumb + `Open in GitHub` chrome, which cloud's shared `InboxDetailFrame`
 * (read-only) doesn't expose slots for — so we surface it as the first right-column section.
 */
function PullRequestBanner({ prUrl, prRef }: { prUrl: string; prRef: ParsedPrUrl }): JSX.Element {
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
            <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                <span className="font-mono text-[13px] text-primary truncate">
                    {prRef.repoSlug}#{prRef.number}
                </span>
                <span className="text-xs text-tertiary leading-none">Pull request</span>
            </div>
            <Tooltip title="Open in GitHub">
                <span className="shrink-0 text-tertiary transition-colors group-hover:text-default">
                    <IconExternal className="text-base" />
                </span>
            </Tooltip>
        </Link>
    )
}

export function PullRequestDetail({ report }: { report: SignalReport }): JSX.Element {
    const prUrl = report.implementation_pr_url ?? null
    const prRef = prUrl ? parsePrUrl(prUrl) : null

    return (
        <InboxDetailFrame
            report={report}
            summary={{ icon: <IconPullRequest />, title: 'Summary' }}
            primaryAction={
                prRef && prUrl ? (
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
            {prRef && prUrl ? <PullRequestBanner prUrl={prUrl} prRef={prRef} /> : null}
        </InboxDetailFrame>
    )
}
