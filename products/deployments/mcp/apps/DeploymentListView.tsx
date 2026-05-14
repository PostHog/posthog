import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView, formatDate } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import { DeploymentView, type DeploymentData } from './DeploymentView'
import { formatDuration, STATUS_LABELS, STATUS_VARIANTS } from './utils'

export interface DeploymentListData {
    count?: number
    results: DeploymentData[]
    _posthogUrl?: string
}

export interface DeploymentListViewProps {
    data: DeploymentListData
    onDeploymentClick?: (deployment: DeploymentData) => Promise<DeploymentData | null>
}

export function DeploymentListView({ data, onDeploymentClick }: DeploymentListViewProps): ReactElement {
    return (
        <ListDetailView<DeploymentData>
            onItemClick={onDeploymentClick}
            backLabel="All deployments"
            getItemName={(d) => d.commit_message || d.id}
            renderDetail={(d) => <DeploymentView deployment={d} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<DeploymentData>[] = [
                    {
                        key: 'commit_message',
                        header: 'Deployment',
                        sortable: true,
                        render: (row): ReactNode => {
                            const label = row.commit_message || row.id
                            const titleEl = onDeploymentClick ? (
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={() => handleClick(row)}
                                    className="h-auto px-0 text-left"
                                >
                                    {label}
                                </Button>
                            ) : (
                                label
                            )
                            return (
                                <span className="flex items-center gap-2">
                                    {titleEl}
                                    {row.is_current && (
                                        <Badge variant="success" className="shrink-0">
                                            Current
                                        </Badge>
                                    )}
                                </span>
                            )
                        },
                    },
                    {
                        key: 'status',
                        header: 'Status',
                        sortable: true,
                        render: (row): ReactNode => {
                            const status = row.status ?? 'queued'
                            return (
                                <Badge variant={STATUS_VARIANTS[status] ?? 'default'}>
                                    {STATUS_LABELS[status] ?? status}
                                </Badge>
                            )
                        },
                    },
                    {
                        key: 'duration_seconds',
                        header: 'Duration',
                        align: 'right',
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground">{formatDuration(row.duration_seconds)}</span>
                        ),
                    },
                    {
                        key: 'created_at',
                        header: 'When',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.created_at ? (
                                <span className="text-muted-foreground">{formatDate(row.created_at)}</span>
                            ) : (
                                <span className="text-muted-foreground">&mdash;</span>
                            ),
                    },
                    {
                        key: 'commit_author_name',
                        header: 'Author',
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground">
                                {row.commit_author_name || row.commit_author_email || '—'}
                            </span>
                        ),
                    },
                ]

                return (
                    <div className="p-4">
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-muted-foreground">
                                    {data.count ?? data.results.length} deployment
                                    {(data.count ?? data.results.length) === 1 ? '' : 's'}
                                </span>
                            </div>
                            <DataTable<DeploymentData>
                                columns={columns}
                                data={data.results}
                                pageSize={10}
                                defaultSort={{ key: 'created_at', direction: 'desc' }}
                                emptyMessage="No deployments found"
                            />
                        </div>
                    </div>
                )
            }}
        />
    )
}
