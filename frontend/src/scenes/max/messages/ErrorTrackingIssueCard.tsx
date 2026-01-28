import { LemonTag } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { MaxErrorTrackingIssuePreview } from '~/queries/schema/schema-assistant-error-tracking'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

interface ErrorTrackingIssueCardProps {
    issue: MaxErrorTrackingIssuePreview
}

export function ErrorTrackingIssueCard({ issue }: ErrorTrackingIssueCardProps): JSX.Element {
    const runtime = getRuntimeFromLib(issue.library)

    return (
        <Link
            to={urls.errorTrackingIssue(issue.id)}
            className="block hover:bg-bg-light px-3 py-2 no-underline text-inherit"
        >
            <div className="flex items-start gap-2">
                <RuntimeIcon runtime={runtime} className="mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{issue.name || 'Unnamed issue'}</div>
                    {issue.description && <div className="text-xs text-muted truncate mt-0.5">{issue.description}</div>}
                    <div className="flex items-center gap-2 flex-wrap mt-1">
                        <LemonTag size="small" type={issue.status === 'active' ? 'warning' : 'default'}>
                            {issue.status}
                        </LemonTag>
                        <span className="text-xs text-muted">{issue.occurrences.toLocaleString()} occurrences</span>
                        <span className="text-xs text-muted">{issue.users.toLocaleString()} users</span>
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
