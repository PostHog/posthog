import { IconPauseFilled, IconXCircle } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import type { DataWarehouseSavedQuerySummary } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { servingSuspension } from './suspension'

export function MaterializationStatusIcon({ view }: { view: DataWarehouseSavedQuerySummary }): JSX.Element | null {
    if (!view.is_materialized) {
        return null
    }
    const suspension = servingSuspension(view.suspended)
    if (suspension) {
        return (
            <Tooltip
                title={
                    <div className="flex flex-col gap-1">
                        <div>
                            Scheduled runs are paused for this view because materialization kept failing. Fix the query,
                            then resume.
                        </div>
                        <div className="opacity-75 line-clamp-4">{suspension.reason}</div>
                    </div>
                }
            >
                <IconPauseFilled className="shrink-0 text-warning" />
            </Tooltip>
        )
    }
    if (view.status === 'Failed') {
        return (
            <Tooltip
                title={
                    <div className="flex flex-col gap-1">
                        <div>The last materialization run failed. Scheduled runs pause if it keeps failing.</div>
                        {view.latest_error ? <div className="opacity-75 line-clamp-4">{view.latest_error}</div> : null}
                    </div>
                }
            >
                <IconXCircle className="shrink-0 text-danger" />
            </Tooltip>
        )
    }
    return null
}
