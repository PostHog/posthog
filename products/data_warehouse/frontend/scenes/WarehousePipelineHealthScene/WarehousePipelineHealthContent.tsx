import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button, Skeleton, Text } from '@posthog/quill'

import { formatAbsoluteTime, formatRelativeTime } from '../WarehouseConsole/warehouseConsoleFormat'
import { type WarehousePageTab, WarehousePageTabs } from '../WarehouseConsole/WarehousePageTabs'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehousePipelineEventData } from './WarehousePipelineEventData'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'
import { WarehousePipelineSources } from './WarehousePipelineSources'
import { WarehousePipelineSourceTables } from './WarehousePipelineSourceTables'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

// PostHog's own data arrives continuously, and sources sync in batches, so each kind has its own tab.
const TABS: WarehousePageTab[] = [
    { value: 'posthog', label: 'PostHog data', 'data-attr': 'warehouse-pipeline-health-tab-posthog' },
    { value: 'sources', label: 'Sources', 'data-attr': 'warehouse-pipeline-health-tab-sources' },
]

/** The page body once the warehouse is ready. It mounts the page logic, so nothing loads before then. */
export function WarehousePipelineHealthContent(): JSX.Element {
    const { managedWarehouseDataStatus, managedWarehouseDataStatusLoading, statusFailed } =
        useValues(warehousePipelineHealthLogic)
    const { loadManagedWarehouseDataStatus, refreshClicked } = useActions(warehousePipelineHealthLogic)

    if (!managedWarehouseDataStatus) {
        return statusFailed ? (
            <WarehouseResourceError
                title="Couldn't load pipelines"
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
            <WarehousePageTabs tabs={TABS} page="pipeline_health">
                {(tab) =>
                    tab === 'sources' ? (
                        <>
                            <WarehousePipelineSources />
                            <WarehousePipelineSourceTables />
                        </>
                    ) : (
                        <WarehousePipelineEventData />
                    )
                }
            </WarehousePageTabs>
        </>
    )
}
