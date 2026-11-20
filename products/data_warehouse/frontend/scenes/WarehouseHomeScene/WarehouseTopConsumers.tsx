import { useActions, useValues } from 'kea'

import { Button, Card, CardContent, CardHeader, CardTitle, Skeleton, Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { formatBytes, formatUsd, parseDecimal } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { warehouseConsoleOverviewLogic } from './warehouseConsoleOverviewLogic'
import { WarehouseHomeLink } from './WarehouseHomeLink'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

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
        body = (
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
                {consumers.map((row) => (
                    <li key={row.key} className="flex min-w-0 items-baseline justify-between gap-3">
                        <Text size="sm" className="min-w-0 truncate">
                            {row.label}
                        </Text>
                        <Text size="xs" variant="muted" className="shrink-0 whitespace-nowrap">
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
        <Card data-attr="warehouse-home-top-consumers">
            <CardHeader>
                <CardTitle>Top logins this month</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                {body}
                <div>
                    <Button
                        size="sm"
                        nativeButton={false}
                        render={
                            <WarehouseHomeLink
                                to={`${urls.warehouseUsage()}?group_by=principal`}
                                section="top_consumers"
                                data-attr="warehouse-home-open-usage-by-login"
                            >
                                See usage by login
                            </WarehouseHomeLink>
                        }
                    />
                </div>
            </CardContent>
        </Card>
    )
}
