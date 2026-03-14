import { useEffect, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

interface ErrorTrackingWidgetProps {
    tileId: number
    config: Record<string, any>
}

interface ErrorIssue {
    id: string
    name: string
    description: string | null
    status: string
    occurrences: number
    sessions: number
    users: number
    first_seen: string
    last_seen: string
}

const STATUS_COLORS: Record<string, string> = {
    active: 'text-danger',
    resolved: 'text-success',
    archived: 'text-muted',
    pending_release: 'text-warning',
    suppressed: 'text-muted',
}

function ErrorTrackingWidget({ config }: ErrorTrackingWidgetProps): JSX.Element {
    const [issues, setIssues] = useState<ErrorIssue[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        setLoading(true)
        const params: Record<string, any> = { limit: 10 }
        if (config.status) {
            params.status = config.status
        }

        api.get('api/projects/@current/error_tracking/issues', params)
            .then((data: any) => {
                setIssues(data.results || [])
                setLoading(false)
            })
            .catch(() => {
                setError('Failed to load error tracking issues')
                setLoading(false)
            })
    }, [config.status])

    if (loading) {
        return (
            <div className="p-4 space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                    <LemonSkeleton key={i} className="h-8 w-full" />
                ))}
            </div>
        )
    }

    if (error) {
        return (
            <div className="p-4 flex flex-col items-center justify-center h-full text-muted">
                <IconWarning className="text-3xl mb-2" />
                <span>{error}</span>
            </div>
        )
    }

    return (
        <div className="h-full flex flex-col overflow-hidden">
            <LemonTable
                dataSource={issues}
                size="small"
                className="flex-1"
                columns={[
                    {
                        title: 'Error',
                        key: 'name',
                        render: (_, issue) => (
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                to={urls.errorTrackingIssue(issue.id)}
                                className="max-w-[300px]"
                            >
                                <span className="truncate">{issue.name || 'Unknown error'}</span>
                            </LemonButton>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        width: 80,
                        render: (_, issue) => (
                            <span className={`text-xs font-medium capitalize ${STATUS_COLORS[issue.status] || ''}`}>
                                {issue.status?.replace('_', ' ')}
                            </span>
                        ),
                    },
                    {
                        title: 'Events',
                        key: 'occurrences',
                        width: 70,
                        align: 'right',
                        render: (_, issue) => <span className="text-xs">{issue.occurrences}</span>,
                    },
                    {
                        title: 'Last seen',
                        key: 'last_seen',
                        width: 120,
                        render: (_, issue) =>
                            issue.last_seen ? <TZLabel time={issue.last_seen} className="text-xs" /> : null,
                    },
                ]}
                rowKey="id"
                emptyState={
                    <div className="text-center py-8 text-muted">
                        <IconWarning className="text-2xl mb-2" />
                        <div>No error issues found</div>
                    </div>
                }
            />
        </div>
    )
}

export default ErrorTrackingWidget
