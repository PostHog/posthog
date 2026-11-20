import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { formatBytes, formatUsd, meterVariant } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { warehouseConsoleOverviewLogic } from './warehouseConsoleOverviewLogic'
import { WarehouseHomeLink } from './WarehouseHomeLink'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseUsageStrip(): JSX.Element {
    const { overviewUsage, overviewUsageLoading, overviewFailed, computeMeter, storageMeter } =
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
        return overviewUsageLoading ? <Skeleton className="h-28 w-full" /> : <></>
    }
    const forecast = overviewUsage.forecast_total_usd
    return (
        <div className="grid grid-cols-1 gap-3 @lg/warehouse-home:grid-cols-3">
            <WarehouseHomeLink to={urls.warehouseUsage()} section="usage_spend" data-attr="warehouse-home-usage-spend">
                <WarehouseStatTile
                    label="Estimated spend this month"
                    value={formatUsd(overviewUsage.total_estimated_cost_usd)}
                    detail={forecast !== null ? `Forecast ${formatUsd(forecast)} est. for the month` : undefined}
                />
            </WarehouseHomeLink>
            <WarehouseHomeLink
                to={urls.warehouseUsage()}
                section="usage_compute"
                data-attr="warehouse-home-usage-compute"
            >
                <WarehouseStatTile
                    label="Compute scanned"
                    value={formatBytes(computeMeter.used)}
                    detail={`of ${formatBytes(computeMeter.free)} free each month`}
                    meterPercent={computeMeter.percent}
                    meterVariant={meterVariant(computeMeter.percent)}
                />
            </WarehouseHomeLink>
            <WarehouseHomeLink
                to={urls.warehouseUsage()}
                section="usage_storage"
                data-attr="warehouse-home-usage-storage"
            >
                <WarehouseStatTile
                    label="Storage"
                    value={`${storageMeter.used.toFixed(2)} GiB-months`}
                    detail={`of ${storageMeter.free.toFixed(0)} GiB-months free each month`}
                    meterPercent={storageMeter.percent}
                    meterVariant={meterVariant(storageMeter.percent)}
                />
            </WarehouseHomeLink>
        </div>
    )
}
