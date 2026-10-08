import posthog from 'posthog-js'

import { LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

export type WorkflowsWidgetRow = {
    id: string
    name: string
    description: string
    status: string
    workflow_type: string
    trigger_type: string | null
    has_email_step: boolean
    updated_at: string | null
    started: number
    completed: number
    failed: number
    email_sent: number
    email_delivered: number
    email_opened: number
    email_bounced: number
}

// Same labels and tag colors as the workflows list, so a row reads the same on both surfaces.
const STATUS_TAGS: Record<string, { label: string; type: LemonTagType }> = {
    active: { label: 'Active', type: 'success' },
    draft: { label: 'Draft', type: 'default' },
    archived: { label: 'Archived', type: 'muted' },
}

const TYPE_TAGS: Record<string, { label: string; type: LemonTagType }> = {
    broadcast: { label: 'Broadcast', type: 'highlight' },
    loop: { label: 'Loop', type: 'highlight' },
    messaging: { label: 'Messaging', type: 'completion' },
    automation: { label: 'Automation', type: 'default' },
}

function WorkflowMetric({ label, value }: { label: string; value: number }): JSX.Element {
    return (
        <span className="inline-flex items-baseline gap-1 whitespace-nowrap text-xs">
            <span className="text-muted">{label}</span>
            <span className="font-semibold tabular-nums text-primary">{humanFriendlyNumber(value)}</span>
        </span>
    )
}

export function WorkflowsWidgetRowItem({ tileId, row }: { tileId: number; row: WorkflowsWidgetRow }): JSX.Element {
    const statusTag = STATUS_TAGS[row.status] ?? STATUS_TAGS.draft
    const typeTag = TYPE_TAGS[row.workflow_type] ?? TYPE_TAGS.automation
    const href = row.workflow_type === 'broadcast' ? urls.broadcast(row.id) : urls.workflow(row.id, 'workflow')

    return (
        <div className="flex flex-col gap-1.5 border-b border-primary px-3 py-2" data-attr="workflows-widget-row">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Link
                    to={href}
                    target="_blank"
                    className="min-w-0 flex-1 truncate font-semibold text-primary"
                    title={row.name || 'Untitled workflow'}
                    onClick={() =>
                        posthog.capture('dashboard widget open workflow clicked', {
                            widget_type: 'workflows_list',
                            tile_id: tileId,
                            workflow_id: row.id,
                        })
                    }
                >
                    {row.name || 'Untitled workflow'}
                </Link>
                <div className="flex shrink-0 items-center gap-1">
                    <LemonTag type={typeTag.type}>{typeTag.label}</LemonTag>
                    <LemonTag type={statusTag.type}>{statusTag.label}</LemonTag>
                </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <WorkflowMetric label="Started" value={row.started} />
                <WorkflowMetric label="Completed" value={row.completed} />
                <WorkflowMetric label="Failed" value={row.failed} />
                {row.has_email_step ? (
                    <>
                        <span className="text-muted" aria-hidden>
                            ·
                        </span>
                        <WorkflowMetric label="Sent" value={row.email_sent} />
                        <WorkflowMetric label="Delivered" value={row.email_delivered} />
                        <WorkflowMetric label="Opened" value={row.email_opened} />
                        <WorkflowMetric label="Bounced" value={row.email_bounced} />
                    </>
                ) : null}
            </div>
        </div>
    )
}
