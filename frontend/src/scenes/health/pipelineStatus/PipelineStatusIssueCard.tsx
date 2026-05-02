import { IconDatabase, IconPlug, IconRevert, IconServer, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { DataHealthIssue } from './pipelineHealthLogic'

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

function getErrorLabelForMaterializedView(error: string | null): JSX.Element | null {
    if (!error) {
        return null
    }

    if (error.includes('Query returned no results')) {
        return (
            <span>
                Query returned no results for this view. This either means you haven't{' '}
                <Link to={urls.revenueSettings()} target="_blank" targetBlankIcon={false}>
                    configured Revenue Analytics
                </Link>{' '}
                properly (missing subscription properties) or the{' '}
                <Link to={urls.dataPipelinesNew('source')} target="_blank" targetBlankIcon={false}>
                    underlying source of data
                </Link>{' '}
                isn't correctly set-up.
            </span>
        )
    }

    return (
        <span>
            Please{' '}
            <Link to="https://posthog.com/support" target="_blank">
                contact support
            </Link>{' '}
            for help resolving this issue.
        </span>
    )
}

export function PipelineStatusIssueCard({
    issue,
    isDismissed,
    onDismiss,
    onUndismiss,
}: {
    issue: DataHealthIssue
    isDismissed?: boolean
    onDismiss?: () => void
    onUndismiss?: () => void
}): JSX.Element {
    const typeLabel = getTypeLabel(issue)
    const statusLabel = getStatusLabel(issue.status)
    const statusTagType = getStatusTagType(issue.status)

    // Materialized views don't have a user-accessible page, so we don't link them
    const showLink = issue.url && issue.type !== 'materialized_view'

    return (
        <div className={`border rounded p-3 bg-surface-primary${isDismissed ? ' opacity-60' : ''}`}>
            <div className="flex items-start gap-2">
                <div className="mt-0.5">{getIssueIcon(issue.type)}</div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        {showLink ? (
                            <Link to={issue.url!} className="font-semibold truncate">
                                {issue.name}
                            </Link>
                        ) : (
                            <span className="font-semibold truncate">{issue.name}</span>
                        )}
                        <LemonTag type={statusTagType} size="small">
                            {statusLabel}
                        </LemonTag>
                        {(onDismiss || onUndismiss) && (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                icon={isDismissed ? <IconRevert /> : <IconX />}
                                tooltip={isDismissed ? 'Undismiss' : 'Dismiss'}
                                onClick={() => (isDismissed ? onUndismiss?.() : onDismiss?.())}
                                className="shrink-0 ml-auto"
                            />
                        )}
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
                    {issue.type === 'materialized_view' && (
                        <div className="text-xs text-muted mt-2">{getErrorLabelForMaterializedView(issue.error)}</div>
                    )}
                </div>
            </div>
        </div>
    )
}
