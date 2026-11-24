import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseStatStrip } from '../WarehouseConsole/WarehouseStatStrip'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { warehouseHomeLogic } from './warehouseHomeLogic'
import { WarehouseRunBars } from './WarehouseRunBars'

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
    } = useValues(warehouseHomeLogic)
    const { retryJobStats } = useActions(warehouseHomeLogic)

    let runTiles: JSX.Element
    if (jobStatsFailed && !jobStats) {
        runTiles = (
            <div className="@4xl:col-span-3">
                <WarehouseResourceError
                    title="Couldn't load run statistics"
                    onRetry={retryJobStats}
                    data-attr="warehouse-home-stats-retry"
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
                    data-attr="warehouse-home-stat-success"
                >
                    <WarehouseRunBars buckets={runBuckets} unit={jobStatsDays === 1 ? 'hour' : 'day'} />
                </WarehouseStatTile>
                <WarehouseStatTile
                    label="Source syncs"
                    value={syncTile.value}
                    detail={syncTile.detail}
                    data-attr="warehouse-home-stat-syncs"
                />
                <WarehouseStatTile
                    label="Materialized views"
                    value={viewTile.value}
                    detail={viewTile.detail}
                    data-attr="warehouse-home-stat-views"
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
                    data-attr="warehouse-home-stat-attention"
                />
            ) : healthIssuesFailed ? (
                <WarehouseStatTile
                    label="Needs attention"
                    value="-"
                    detail="Couldn't load health"
                    data-attr="warehouse-home-stat-attention"
                />
            ) : (
                <Skeleton className="h-24 w-full" />
            )}
        </WarehouseStatStrip>
    )
}
