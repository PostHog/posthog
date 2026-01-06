import { useActions, useValues } from 'kea'

import { IconDatabase, IconPlug, IconRefresh, IconServer } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { IconWithBadge } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { DataHealthIssue, sidePanelHealthLogic } from './sidePanelHealthLogic'

export const SidePanelHealthIcon = (props: { className?: string }): JSX.Element => {
    const { issueCount, healthStatus } = useValues(sidePanelHealthLogic)

    const title =
        issueCount > 0 ? `${issueCount} pipeline issue${issueCount === 1 ? '' : 's'}` : 'All pipelines healthy'

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge content={issueCount > 0 ? '!' : undefined} status={healthStatus}>
                    <IconDatabase />
                </IconWithBadge>
            </span>
        </Tooltip>
    )
}

export function SidePanelHealth(): JSX.Element {
    const { issues, healthIssuesLoading, hasErrors, issueCount } = useValues(sidePanelHealthLogic)
    const { loadHealthIssues } = useActions(sidePanelHealthLogic)

    return (
        <div className="flex flex-col h-full">
            <SidePanelPaneHeader title="Pipeline status">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconRefresh />}
                    disabledReason={healthIssuesLoading ? 'Refreshing...' : undefined}
                    onClick={() => loadHealthIssues()}
                >
                    {healthIssuesLoading ? 'Refreshing...' : 'Refresh'}
                </LemonButton>
            </SidePanelPaneHeader>

            <div className="flex-1 overflow-y-auto p-3">
                {healthIssuesLoading && issues.length === 0 ? (
                    <div className="space-y-3">
                        <LemonSkeleton className="h-20" />
                        <LemonSkeleton className="h-20" />
                    </div>
                ) : hasErrors ? (
                    <div className="text-center text-muted p-4">
                        Error loading health information. Please try again later.
                    </div>
                ) : issueCount === 0 ? (
                    <LemonBanner type="success" hideIcon={false}>
                        <p className="font-semibold">All data pipelines healthy</p>
                        <p className="text-sm mt-1">
                            Your sources, syncs, destinations, and transformations are running without issues.
                        </p>
                    </LemonBanner>
                ) : (
                    <>
                        <LemonBanner type="warning" hideIcon={false} className="mb-4">
                            <p className="font-semibold">
                                {issueCount} issue{issueCount === 1 ? '' : 's'} need{issueCount === 1 ? 's' : ''}{' '}
                                attention
                            </p>
                            <p className="text-sm mt-1">
                                These data pipelines have failed or been disabled and may affect your data.
                            </p>
                        </LemonBanner>

                        <div className="space-y-3">
                            {issues.map((issue: DataHealthIssue) => (
                                <HealthIssueCard key={issue.id} issue={issue} />
                            ))}
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

function getTypeLabel(issue: DataHealthIssue): string {
    switch (issue.type) {
        case 'materialized_view':
            return 'Materialized view'
        case 'external_data_sync':
            return issue.source_type || 'Data sync'
        case 'source':
            return issue.source_type || 'Source'
        case 'destination':
            return 'Destination'
        case 'transformation':
            return 'Transformation'
        default:
            return 'Unknown'
    }
}

function getStatusLabel(status: DataHealthIssue['status']): string {
    switch (status) {
        case 'failed':
            return 'Failed'
        case 'disabled':
            return 'Disabled'
        case 'degraded':
            return 'Degraded'
        case 'billing_limit':
            return 'Billing limit'
        default:
            return 'Error'
    }
}

function getStatusTagType(status: DataHealthIssue['status']): 'danger' | 'warning' {
    return status === 'degraded' ? 'warning' : 'danger'
}

function getIssueIcon(type: DataHealthIssue['type']): JSX.Element {
    switch (type) {
        case 'materialized_view':
            return <IconServer className="text-muted text-lg" />
        case 'external_data_sync':
        case 'source':
            return <IconDatabase className="text-muted text-lg" />
        case 'destination':
        case 'transformation':
            return <IconPlug className="text-muted text-lg" />
        default:
            return <IconDatabase className="text-muted text-lg" />
    }
}

function HealthIssueCard({ issue }: { issue: DataHealthIssue }): JSX.Element {
    const typeLabel = getTypeLabel(issue)
    const statusLabel = getStatusLabel(issue.status)
    const statusTagType = getStatusTagType(issue.status)

    return (
        <div className="border rounded p-3 bg-surface-primary">
            <div className="flex items-start gap-2">
                <div className="mt-0.5">{getIssueIcon(issue.type)}</div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        {issue.url ? (
                            <Link to={issue.url} className="font-semibold truncate">
                                {issue.name}
                            </Link>
                        ) : (
                            <span className="font-semibold truncate">{issue.name}</span>
                        )}
                        <LemonTag type={statusTagType} size="small">
                            {statusLabel}
                        </LemonTag>
                    </div>
                    <div className="text-xs text-muted mb-2">{typeLabel}</div>
                    {issue.error && (
                        <div className="text-xs bg-surface-secondary rounded p-2 mb-2 break-words">
                            <code className="text-danger">{issue.error}</code>
                        </div>
                    )}
                    {issue.failed_at && (
                        <div className="text-xs text-muted">
                            {statusLabel} {humanFriendlyDetailedTime(issue.failed_at)}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
