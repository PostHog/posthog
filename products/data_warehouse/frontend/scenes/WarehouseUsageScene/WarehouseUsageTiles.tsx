import { useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import {
    formatBytes,
    formatPercent,
    formatUsd,
    meterVariant,
    parseDecimal,
} from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { warehouseUsageLogic } from './warehouseUsageLogic'

export function WarehouseUsageTiles(): JSX.Element {
    const { usage, usageLoading, computeMeter, storageMeter, budgetPercent, isCurrentMonth } =
        useValues(warehouseUsageLogic)

    if (!usage || !computeMeter || !storageMeter) {
        return (
            <div className="grid grid-cols-1 gap-3 @lg/warehouse-usage:grid-cols-2 @3xl/warehouse-usage:grid-cols-4">
                {usageLoading && [0, 1, 2, 3].map((index) => <Skeleton key={index} className="h-28 w-full" />)}
            </div>
        )
    }

    const failedBytes = usage.compute.failed_billable_bytes
    const hasBudget = usage.budget.monthly_budget_usd !== null

    return (
        <div
            className="grid grid-cols-1 gap-3 @lg/warehouse-usage:grid-cols-2 @3xl/warehouse-usage:grid-cols-4"
            data-attr="warehouse-usage-tiles"
        >
            <WarehouseStatTile
                label="Compute scanned"
                value={formatBytes(computeMeter.used)}
                detail={`of ${formatBytes(computeMeter.free)} free each month`}
                note={
                    failedBytes > 0 ? `Includes ${formatBytes(failedBytes)} from failed or canceled queries` : undefined
                }
                meterPercent={computeMeter.percent}
                meterVariant={meterVariant(computeMeter.percent)}
                data-attr="warehouse-usage-tile-compute"
            />
            <WarehouseStatTile
                label="Storage"
                value={`${parseDecimal(usage.storage.gib_months).toFixed(2)} GiB-months`}
                detail={`of ${parseDecimal(usage.storage.free_gib_months).toFixed(0)} GiB-months free each month`}
                meterPercent={storageMeter.percent}
                meterVariant={meterVariant(storageMeter.percent)}
                data-attr="warehouse-usage-tile-storage"
            />
            <WarehouseStatTile
                label="Estimated spend"
                value={formatUsd(usage.total_estimated_cost_usd)}
                detail={`Compute ${formatUsd(usage.compute.estimated_cost_usd)} est., storage ${formatUsd(usage.storage.estimated_cost_usd)} est.`}
                data-attr="warehouse-usage-tile-spend"
            />
            {isCurrentMonth && usage.forecast_total_usd !== null ? (
                <WarehouseStatTile
                    label="Forecast for this month"
                    value={formatUsd(usage.forecast_total_usd)}
                    detail="Estimated at the current pace"
                    data-attr="warehouse-usage-tile-forecast"
                />
            ) : null}
            {hasBudget ? (
                <WarehouseStatTile
                    label="Budget used"
                    value={budgetPercent == null ? '-' : formatPercent(budgetPercent / 100)}
                    detail={`of ${formatUsd(usage.budget.monthly_budget_usd)} monthly budget (est.)`}
                    meterPercent={budgetPercent}
                    meterVariant={meterVariant(budgetPercent)}
                    data-attr="warehouse-usage-tile-budget"
                />
            ) : null}
        </div>
    )
}
