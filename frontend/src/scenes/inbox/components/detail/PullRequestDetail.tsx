import { IconExternal, IconPullRequest } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
        />
    )
}
