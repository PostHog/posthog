import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { formatBytes, formatUsd } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseStatStrip } from '../WarehouseConsole/WarehouseStatStrip'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { warehouseConsoleOverviewLogic } from './warehouseConsoleOverviewLogic'
import { WarehouseHomeLink } from './WarehouseHomeLink'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseUsageStrip(): JSX.Element {
    const { overviewUsage, overviewUsageLoading, overviewFailed, computeMeter, storageMeter, workload } =
        useValues(warehouseConsoleOverviewLogic)
    const { retryOverview } = useActions(warehouseConsoleOverviewLogic)

    if (overviewFailed && !overviewUsage) {
        return (
            <WarehouseResourceError
                title="Couldn't load usage"
                onRetry={retryOverview}
                data-attr="warehouse-home-usage-retry"
            />
        )
    }
    if (!overviewUsage || !computeMeter || !storageMeter) {
        return overviewUsageLoading ? <Skeleton className="h-24 w-full" /> : <></>
    }
    const forecast = overviewUsage.forecast_total_usd
    const computeOver = computeMeter.used > computeMeter.free
    return (
        <WarehouseStatStrip>
            <WarehouseHomeLink
                to={urls.warehouseUsage()}
                section="usage_spend"
                className="block h-full"
                data-attr="warehouse-home-usage-spend"
            >
                <WarehouseStatTile
                    label="Estimated spend"
                    value={formatUsd(overviewUsage.total_estimated_cost_usd)}
                    detail={forecast !== null ? `Forecast ${formatUsd(forecast)} est.` : 'This month so far'}
                />
            </WarehouseHomeLink>
            <WarehouseHomeLink
                to={urls.warehouseUsage()}
                section="usage_compute"
                className="block h-full"
                data-attr="warehouse-home-usage-compute"
            >
                <WarehouseStatTile
                    label="Compute scanned"
                    value={formatBytes(computeMeter.used)}
                    detail={
                        computeOver
                            ? `${formatBytes(computeMeter.free)} free, ${formatBytes(computeMeter.used - computeMeter.free)} billable`
                            : `of ${formatBytes(computeMeter.free)} free`
                    }
                    meter={{ used: computeMeter.used, limit: computeMeter.free }}
                />
            </WarehouseHomeLink>
            <WarehouseHomeLink
                to={urls.warehouseUsage()}
                section="usage_storage"
                className="block h-full"
                data-attr="warehouse-home-usage-storage"
            >
                <WarehouseStatTile
                    label="Storage"
                    value={`${Number(storageMeter.used.toFixed(2))} GiB-months`}
                    detail={
                        storageMeter.used > storageMeter.free
                            ? `${Number(storageMeter.free.toFixed(0))} GiB-months free, ${Number((storageMeter.used - storageMeter.free).toFixed(0))} billable`
                            : `of ${Number(storageMeter.free.toFixed(0))} GiB-months free`
                    }
                    meter={{ used: storageMeter.used, limit: storageMeter.free }}
                />
            </WarehouseHomeLink>
            <WarehouseHomeLink
                to={urls.warehouseQueries()}
                section="live_workload"
                className="block h-full"
                data-attr="warehouse-home-open-queries"
            >
                <WarehouseStatTile
                    label="Running now"
                    value={workload ? String(workload.running) : '-'}
                    detail={workload ? `${workload.queued} queued` : 'Live data unavailable'}
                />
            </WarehouseHomeLink>
        </WarehouseStatStrip>
    )
}
