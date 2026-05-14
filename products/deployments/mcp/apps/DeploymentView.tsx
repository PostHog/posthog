import type { ReactElement } from 'react'

import { DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Button, Card, CardContent } from '@posthog/quill'

import { formatDuration, STATUS_LABELS, STATUS_VARIANTS } from './utils'

export interface DeploymentData {
    id: string
    status: string
    is_current?: boolean
    started_at?: string | null
    finished_at?: string | null
    created_at: string
    duration_seconds?: number | null
    commit_sha?: string
    commit_message?: string
    commit_author_name?: string
    commit_author_email?: string
    repo_url?: string
    branch?: string
    deployment_url?: string
    preview_image_url?: string
    trigger_kind?: string
    triggered_by_deployment?: string | null
    _posthogUrl?: string
}

export interface DeploymentViewProps {
    deployment: DeploymentData
}

export function DeploymentView({ deployment: d }: DeploymentViewProps): ReactElement {
    const failed = d.status === 'error'

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold">{d.commit_message || d.commit_sha || d.id}</span>
                        {d.is_current && <Badge variant="success">Current</Badge>}
                        <Badge variant={STATUS_VARIANTS[d.status] ?? 'default'}>
                            {STATUS_LABELS[d.status] ?? d.status}
                        </Badge>
                        {d.trigger_kind && d.trigger_kind !== 'git' && (
                            <Badge variant="default">{d.trigger_kind}</Badge>
                        )}
                    </div>
                    <span className="text-xs text-muted-foreground font-mono">{d.id}</span>
                </div>

                {d.preview_image_url ? (
                    <Card>
                        <CardContent className="p-0 overflow-hidden">
                            <img
                                src={d.preview_image_url}
                                alt={`Preview of ${d.commit_message || d.id}`}
                                className="w-full object-cover"
                            />
                        </CardContent>
                    </Card>
                ) : failed ? (
                    <Card>
                        <CardContent className="flex items-center justify-center py-8 text-destructive font-semibold">
                            Build failed
                        </CardContent>
                    </Card>
                ) : null}

                <Card>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                { label: 'Duration', value: formatDuration(d.duration_seconds) },
                                { label: 'Deployed', value: formatDate(d.created_at) },
                                ...(d.branch ? [{ label: 'Branch', value: d.branch }] : []),
                                ...(d.commit_author_name || d.commit_author_email
                                    ? [
                                          {
                                              label: 'Author',
                                              value: d.commit_author_name || d.commit_author_email || 'Unknown',
                                          },
                                      ]
                                    : []),
                                ...(d.commit_sha ? [{ label: 'Commit', value: d.commit_sha.slice(0, 7) }] : []),
                            ]}
                        />
                    </CardContent>
                </Card>

                <div className="flex flex-wrap gap-2">
                    {d.repo_url && d.commit_sha && (
                        <Button asChild variant="outline" size="sm">
                            <a href={`${d.repo_url}/commit/${d.commit_sha}`} target="_blank" rel="noreferrer">
                                View source
                            </a>
                        </Button>
                    )}
                    {d.deployment_url && (
                        <Button asChild size="sm">
                            <a href={d.deployment_url} target="_blank" rel="noreferrer">
                                View live
                            </a>
                        </Button>
                    )}
                </div>
            </div>
        </div>
    )
}
