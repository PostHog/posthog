import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Skeleton, Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { formatBytes, formatUsd, parseDecimal } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseSectionLink } from '../WarehouseConsole/WarehouseSectionLink'
import { WarehouseShareBar } from '../WarehouseConsole/WarehouseShareBar'
import { warehouseConsoleOverviewLogic } from './warehouseConsoleOverviewLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseTopConsumers(): JSX.Element {
    const { consumers, overviewUsage, overviewFailed } = useValues(warehouseConsoleOverviewLogic)
    const { retryOverview } = useActions(warehouseConsoleOverviewLogic)

    let body: JSX.Element
    if (overviewFailed && !overviewUsage) {
        body = (
            <WarehouseResourceError
                title="Couldn't load usage"
                onRetry={retryOverview}
                data-attr="warehouse-home-consumers-retry"
            />
        )
    } else if (!overviewUsage) {
        body = <Skeleton className="h-16 w-full" />
    } else if (consumers.length === 0) {
        body = (
            <Text size="sm" variant="muted">
                No queries yet this month.
            </Text>
        )
    } else {
        const totalBytes = Math.max(overviewUsage.compute.billable_bytes, 1)
        body = (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {consumers.map((row) => (
                    <li key={row.key} className="flex min-w-0 items-center gap-3">
                        <Text size="sm" className="min-w-0 flex-1 truncate" title={row.key}>
                            {row.label}
                        </Text>
                        <WarehouseShareBar fraction={row.billable_bytes / totalBytes} label={`${row.label} share`} />
                        <Text
                            size="xs"
                            variant="muted"
                            className="w-44 shrink-0 whitespace-nowrap text-right tabular-nums"
                        >
                            {formatBytes(row.billable_bytes)} ·{' '}
                            {parseDecimal(row.estimated_cost_share_usd) > 0
                                ? `${formatUsd(row.estimated_cost_share_usd)} est.`
                                : 'Free tier'}
                        </Text>
                    </li>
                ))}
            </ul>
        )
    }

    return (
        <WarehouseSection
            title="Top logins this month"
            data-attr="warehouse-home-top-consumers"
            controls={
                <WarehouseSectionLink
                    to={`${urls.warehouseUsage()}?group_by=principal`}
                    onClick={() => posthog.capture('warehouse home link clicked', { section: 'top_consumers' })}
                    data-attr="warehouse-home-open-usage-by-login"
                >
                    View usage
                </WarehouseSectionLink>
            }
        >
            {body}
        </WarehouseSection>
    )
}
