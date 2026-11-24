import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button, Skeleton, Text } from '@posthog/quill'

import { formatAbsoluteTime, formatRelativeTime } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehousePipelineEventData } from './WarehousePipelineEventData'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'
import { WarehousePipelineRuns } from './WarehousePipelineRuns'
import { WarehousePipelineSources } from './WarehousePipelineSources'
import { WarehousePipelineSourceTables } from './WarehousePipelineSourceTables'
import { WarehousePipelineStrip } from './WarehousePipelineStrip'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

/** The page body once the warehouse is ready. It mounts the page logic, so nothing loads before then. */
export function WarehousePipelineHealthContent(): JSX.Element {
    const { managedWarehouseDataStatus, managedWarehouseDataStatusLoading, statusFailed } =
        useValues(warehousePipelineHealthLogic)
    const { loadManagedWarehouseDataStatus, refreshClicked } = useActions(warehousePipelineHealthLogic)

    if (!managedWarehouseDataStatus) {
        return statusFailed ? (
            <WarehouseResourceError
                title="Couldn't load pipeline health"
                onRetry={() => loadManagedWarehouseDataStatus()}
                data-attr="warehouse-pipeline-health-retry"
            />
        ) : (
            <Skeleton className="h-40 w-full" />
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
                    onClick={() => refreshClicked()}
                    data-attr="warehouse-pipeline-health-refresh"
                >
                    <IconRefresh />
                    Refresh
                </Button>
            </div>
            <WarehousePipelineStrip />
            <WarehousePipelineRuns />
            <WarehousePipelineEventData />
            <WarehousePipelineSources />
            <WarehousePipelineSourceTables />
        </>
    )
}
