import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconRefresh } from '@posthog/icons'
import { Button, Skeleton, Text } from '@posthog/quill'

import { managedWarehouseDataStatusLogic } from '../DataOpsScene/tabs/managedWarehouseDataStatusLogic'
import { formatAbsoluteTime, formatRelativeTime } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseReadinessDatasets } from './WarehouseReadinessDatasets'
import { WarehouseReadinessSources } from './WarehouseReadinessSources'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

/** The "Data readiness" tab of Storage: backfill status of Events and Persons, and the imported sources. */
export function WarehouseReadiness(): JSX.Element {
    const { managedWarehouseDataStatus, managedWarehouseDataStatusLoading } = useValues(managedWarehouseDataStatusLogic)
    const { loadManagedWarehouseDataStatus } = useActions(managedWarehouseDataStatusLogic)

    if (!managedWarehouseDataStatus) {
        return managedWarehouseDataStatusLoading ? (
            <Skeleton className="h-40 w-full" />
        ) : (
            <WarehouseResourceError
                title="Couldn't load data readiness"
                onRetry={() => loadManagedWarehouseDataStatus()}
                data-attr="warehouse-readiness-retry"
            />
        )
    }
    return (
        <>
            <div className="flex flex-wrap items-center justify-end gap-3">
                <Text
                    size="xs"
                    variant="muted"
                    title={formatAbsoluteTime(managedWarehouseDataStatus.generated_at)}
                    render={<span />}
                >
                    Checked {formatRelativeTime(managedWarehouseDataStatus.generated_at)}
                </Text>
                <Button
                    loading={managedWarehouseDataStatusLoading}
                    disabled={managedWarehouseDataStatusLoading}
                    onClick={() => {
                        posthog.capture('warehouse readiness refresh clicked')
                        loadManagedWarehouseDataStatus()
                    }}
                    data-attr="warehouse-readiness-refresh"
                >
                    <IconRefresh />
                    Refresh
                </Button>
            </div>
            <WarehouseReadinessDatasets />
            <WarehouseReadinessSources />
        </>
    )
}
