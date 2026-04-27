import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { MaxErrorTrackingIssuePreview } from '~/queries/schema/schema-assistant-error-tracking'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

interface ErrorTrackingIssueCardProps {
    issue: MaxErrorTrackingIssuePreview
    showUserCount?: boolean
}

function shortenUrl(url: string, maxLength: number = 60): string {
    if (url.length <= maxLength) {
        return url
    }
    try {
        const parsed = new URL(url)
        const pathPreview = parsed.pathname.length > 30 ? `${parsed.pathname.slice(0, 27)}…` : parsed.pathname
        return `${parsed.host}${pathPreview}`
    } catch {
        return `${url.slice(0, maxLength - 1)}…`
    }
}

export function ErrorTrackingIssueCard({ issue, showUserCount = true }: ErrorTrackingIssueCardProps): JSX.Element {
    const runtime = getRuntimeFromLib(issue.library)
    const isLikelyNoise = !!issue.noise_reason

    return (
        <Link
            to={urls.errorTrackingIssue(issue.id)}
            className="block hover:bg-bg-light px-3 py-2 no-underline text-inherit"
        >
            <div className={`flex items-start gap-2 ${isLikelyNoise ? 'opacity-70' : ''}`}>
                <RuntimeIcon runtime={runtime} className="mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                        <span className="font-medium truncate">{issue.name || 'Unnamed issue'}</span>
                        {isLikelyNoise && (
                            <Tooltip title={issue.noise_reason ?? 'Likely third-party noise'}>
                                <LemonTag size="small" type="muted">
                                    Likely noise
                                </LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    {issue.description && <div className="text-xs text-muted truncate mt-0.5">{issue.description}</div>}
                    {issue.url && (
                        <div className="text-xs text-muted truncate mt-0.5" title={issue.url}>
                            {shortenUrl(issue.url)}
                        </div>
                    )}
                    <div className="flex items-center gap-2 flex-wrap mt-1">
                        <LemonTag size="small" type={issue.status === 'active' ? 'warning' : 'default'}>
                            {issue.status}
                        </LemonTag>
                        <span className="text-xs text-muted">{issue.occurrences.toLocaleString()} occurrences</span>
                        {showUserCount && (
                            <span className="text-xs text-muted">{issue.users.toLocaleString()} users</span>
                        )}
                        {issue.last_seen && (
                            <span className="text-xs text-muted">
                                <TZLabel time={issue.last_seen} />
                            </span>
                        )}
                    </div>
                </div>
            </div>
        </Link>
    )
}
