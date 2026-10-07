import posthog from 'posthog-js'

import * as workflowsPng from '@posthog/brand/hoggies/png/workflows'
import { LemonSkeleton, LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import {
    WIDGET_LIST_COUNT_WORKFLOWS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { parseWorkflowsWidgetConfig } from './workflowsWidgetConfigValidation'

const HedgehogWorkflows = pngHoggie(workflowsPng)

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

export type WorkflowsWidgetResult = {
    results?: WorkflowsWidgetRow[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
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

function WorkflowsWidgetRowItem({ tileId, row }: { tileId: number; row: WorkflowsWidgetRow }): JSX.Element {
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

function WorkflowsWidgetLoadingState(): JSX.Element {
    return (
        <WidgetCardContent>
            <div className="flex flex-col" aria-busy aria-label="Loading workflows">
                {Array.from({ length: 4 }, (_, index) => (
                    <div key={index} className="flex flex-col gap-2 border-b border-primary px-3 py-2" aria-hidden>
                        <div className="flex items-center gap-2">
                            <LemonSkeleton className="h-4 w-40" />
                            <LemonSkeleton className="ml-auto h-5 w-16 rounded" />
                            <LemonSkeleton className="h-5 w-12 rounded" />
                        </div>
                        <LemonSkeleton className="h-3 w-3/4" />
                    </div>
                ))}
            </div>
        </WidgetCardContent>
    )
}

export function WorkflowsWidget({
    tileId,
    config,
    result,
    loading,
    error,
    onRefresh,
}: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as WorkflowsWidgetResult | null | undefined
    const rows = payload?.results ?? []
    const parsedConfig = parseWorkflowsWidgetConfig(config)
    const hasActiveFilters = parsedConfig.status !== 'all' || parsedConfig.workflowType !== 'all'

    if (loading) {
        return <WorkflowsWidgetLoadingState />
    }
    if (error) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage variant="error" onRefresh={onRefresh} refreshing={loading}>
                    Couldn't load workflow activity. Try again.
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }
    if (rows.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="workflows-widget-empty-state"
                    >
                        <HedgehogWorkflows className="size-20 shrink-0" />
                        {hasActiveFilters ? (
                            <>
                                <p className="m-0 text-base font-semibold text-primary">No workflows found</p>
                                <p className="m-0 text-sm text-muted">
                                    No workflows matched the status and type filters.
                                </p>
                            </>
                        ) : (
                            <>
                                <p className="m-0 text-base font-semibold text-primary">No workflows yet</p>
                                <p className="m-0 text-sm text-muted">
                                    Send messages and run automations when your users do something.
                                </p>
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    to={urls.workflows()}
                                    targetBlank
                                    onClick={() =>
                                        posthog.capture('dashboard widget create workflow clicked', {
                                            widget_type: 'workflows_list',
                                            tile_id: tileId,
                                        })
                                    }
                                >
                                    New workflow
                                </LemonButton>
                            </>
                        )}
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }
    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col">
                    {rows.map((row) => (
                        <WorkflowsWidgetRowItem key={row.id} tileId={tileId} row={row} />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={rows.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_WORKFLOWS}
                    hasMore={payload?.hasMore}
                    dataAttr="workflows-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
