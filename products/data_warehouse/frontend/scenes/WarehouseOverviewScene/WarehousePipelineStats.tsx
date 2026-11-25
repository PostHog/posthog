import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseRunBars } from '../WarehouseConsole/WarehouseRunBars'
import { WarehouseStatStrip } from '../WarehouseConsole/WarehouseStatStrip'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { warehouseOverviewLogic } from './warehouseOverviewLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

/** How pipelines are doing overall: run success, source syncs, materialized views and what needs attention. */
export function WarehousePipelineStats(): JSX.Element {
    const {
        jobStats,
        jobStatsFailed,
        jobStatsDays,
        runBuckets,
        runSuccess,
        syncTile,
        viewTile,
        attentionTile,
        healthIssuesFailed,
    } = useValues(warehouseOverviewLogic)
    const { retryJobStats } = useActions(warehouseOverviewLogic)

    let runTiles: JSX.Element
    if (jobStatsFailed && !jobStats) {
        runTiles = (
            <div className="@4xl:col-span-3">
                <WarehouseResourceError
                    title="Couldn't load run statistics"
                    onRetry={retryJobStats}
                    data-attr="warehouse-overview-stats-retry"
                />
            </div>
        )
    } else if (!jobStats || !runSuccess || !syncTile || !viewTile) {
        runTiles = <Skeleton className="h-24 w-full @4xl:col-span-3" />
    } else {
        runTiles = (
            <>
                <WarehouseStatTile
                    label="Run success"
                    value={runSuccess.value}
                    detail={runSuccess.detail}
                    data-attr="warehouse-overview-stat-success"
                >
                    <WarehouseRunBars buckets={runBuckets} unit={jobStatsDays === 1 ? 'hour' : 'day'} />
                </WarehouseStatTile>
                <WarehouseStatTile
                    label="Source syncs"
                    value={syncTile.value}
                    detail={syncTile.detail}
                    data-attr="warehouse-overview-stat-syncs"
                />
                <WarehouseStatTile
                    label="Materialized views"
                    value={viewTile.value}
                    detail={viewTile.detail}
                    data-attr="warehouse-overview-stat-views"
                />
            </>
        )
    }

    return (
        <WarehouseStatStrip>
            {runTiles}
            {attentionTile ? (
                <WarehouseStatTile
                    label="Needs attention"
                    value={attentionTile.value}
                    detail={attentionTile.detail}
                    tone={attentionTile.danger ? 'danger' : 'default'}
                    data-attr="warehouse-overview-stat-attention"
                />
            ) : healthIssuesFailed ? (
                <WarehouseStatTile
                    label="Needs attention"
                    value="-"
                    detail="Couldn't load health"
                    data-attr="warehouse-overview-stat-attention"
                />
            ) : (
                <Skeleton className="h-24 w-full" />
            )}
        </WarehouseStatStrip>
    )
}
