import posthog from 'posthog-js'

import * as workflowsPng from '@posthog/brand/hoggies/png/workflows'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
import { WorkflowsWidgetRowItem, type WorkflowsWidgetRow } from './WorkflowsWidgetRowItem'

const HedgehogWorkflows = pngHoggie(workflowsPng)

export type WorkflowsWidgetResult = {
    results?: WorkflowsWidgetRow[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
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
