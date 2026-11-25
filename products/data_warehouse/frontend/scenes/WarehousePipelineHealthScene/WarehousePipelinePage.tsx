import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

/** Mounts the page logic once the warehouse is ready, and shows the body only after the status has loaded. */
function WarehousePipelineStatusGate({ children }: { children: React.ReactNode }): JSX.Element {
    const { managedWarehouseDataStatus, statusFailed } = useValues(warehousePipelineHealthLogic)
    const { loadManagedWarehouseDataStatus } = useActions(warehousePipelineHealthLogic)

    if (!managedWarehouseDataStatus) {
        return statusFailed ? (
            <WarehouseResourceError
                title="Couldn't load warehouse data status"
                onRetry={() => loadManagedWarehouseDataStatus()}
                data-attr="warehouse-pipeline-health-retry"
            />
        ) : (
            <Skeleton className="h-40 w-full" />
        )
    }
    return <>{children}</>
}

function WarehousePipelineBody({ page, children }: { page: string; children: React.ReactNode }): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page={page} />
    }
    return <WarehousePipelineStatusGate>{children}</WarehousePipelineStatusGate>
}

/** The shell of the two pages on data landing in the warehouse: PostHog data and Source data. */
export function WarehousePipelinePage({
    scene,
    page,
    children,
}: {
    scene: Scene.WarehousePostHogData | Scene.WarehouseSourceData
    /** Names the page in the console state events. */
    page: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[scene].name}
                    description={sceneConfigurations[scene].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-pipeline-health flex flex-col gap-4">
                    <WarehousePipelineBody page={page}>{children}</WarehousePipelineBody>
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
