import { useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { formatBytes, formatPercent, formatUsd, parseDecimal } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseStatStrip } from '../WarehouseConsole/WarehouseStatStrip'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { warehouseUsageLogic } from './warehouseUsageLogic'

function allowanceDetail(used: number, free: number, freeText: string, overText: (over: number) => string): string {
    return used > free ? `${freeText} free, ${overText(used - free)} billable` : `of ${freeText} free`
}

export function WarehouseUsageTiles(): JSX.Element {
    const { usage, usageLoading, computeMeter, storageMeter, budgetPercent, isCurrentMonth } =
        useValues(warehouseUsageLogic)

    if (!usage || !computeMeter || !storageMeter) {
        return (
            <WarehouseStatStrip>
                {usageLoading && [0, 1, 2, 3].map((index) => <Skeleton key={index} className="h-24 w-full" />)}
            </WarehouseStatStrip>
        )
    }

    const failedBytes = usage.compute.failed_billable_bytes
    const budget = usage.budget.monthly_budget_usd
    const hasBudget = budget !== null
    const forecast = usage.forecast_total_usd
    const spendDetail =
        hasBudget && isCurrentMonth && forecast !== null
            ? `Forecast ${formatUsd(forecast)} est.`
            : `Compute ${formatUsd(usage.compute.estimated_cost_usd)}, storage ${formatUsd(usage.storage.estimated_cost_usd)}`

    return (
        <WarehouseStatStrip data-attr="warehouse-usage-tiles">
            <WarehouseStatTile
                label="Compute scanned"
                value={formatBytes(computeMeter.used)}
                detail={allowanceDetail(
                    computeMeter.used,
                    computeMeter.free,
                    formatBytes(computeMeter.free),
                    formatBytes
                )}
                note={
                    failedBytes > 0 ? `Includes ${formatBytes(failedBytes)} from failed or canceled queries` : undefined
                }
                meter={{ used: computeMeter.used, limit: computeMeter.free }}
                data-attr="warehouse-usage-tile-compute"
            />
            <WarehouseStatTile
                label="Storage"
                value={`${Number(storageMeter.used.toFixed(2))} GiB-months`}
                detail={allowanceDetail(
                    storageMeter.used,
                    storageMeter.free,
                    `${Number(storageMeter.free.toFixed(0))} GiB-months`,
                    (over) => String(Number(over.toFixed(0)))
                )}
                meter={{ used: storageMeter.used, limit: storageMeter.free }}
                data-attr="warehouse-usage-tile-storage"
            />
            <WarehouseStatTile
                label="Estimated spend"
                value={formatUsd(usage.total_estimated_cost_usd)}
                detail={spendDetail}
                data-attr="warehouse-usage-tile-spend"
            />
            {hasBudget ? (
                <WarehouseStatTile
                    label="Budget used"
                    value={budgetPercent == null ? '-' : formatPercent(budgetPercent / 100)}
                    detail={`of ${formatUsd(budget)} monthly budget (est.)`}
                    meter={{
                        used: parseDecimal(usage.total_estimated_cost_usd),
                        limit: parseDecimal(budget),
                        tone: 'budget',
                    }}
                    data-attr="warehouse-usage-tile-budget"
                />
            ) : isCurrentMonth && forecast !== null ? (
                <WarehouseStatTile
                    label="Forecast for this month"
                    value={formatUsd(forecast)}
                    detail="Estimated at the current pace"
                    data-attr="warehouse-usage-tile-forecast"
                />
            ) : null}
        </WarehouseStatStrip>
    )
}
