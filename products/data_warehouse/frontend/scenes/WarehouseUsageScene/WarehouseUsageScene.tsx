import { useActions, useValues } from 'kea'

import { Skeleton, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseSpendControls } from './WarehouseSpendControls'
import { WarehouseUsageBreakdown } from './WarehouseUsageBreakdown'
import { WarehouseUsageCharts } from './WarehouseUsageCharts'
import { type UsagePeriod, warehouseUsageLogic } from './warehouseUsageLogic'
import { WarehouseUsageTiles } from './WarehouseUsageTiles'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export const scene: SceneExport = {
    component: WarehouseUsageScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

const PERIOD_OPTIONS: { value: UsagePeriod; label: string }[] = [
    { value: 'current_month', label: 'This month' },
    { value: 'last_month', label: 'Last month' },
]

function WarehouseUsageContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)
    const { usage, usageLoading, usageFailed, period } = useValues(warehouseUsageLogic)
    const { setPeriod, retryUsage } = useActions(warehouseUsageLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page="usage" />
    }

    return (
        <>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <ToggleGroup
                    variant="outline"
                    size="sm"
                    value={[period]}
                    onValueChange={(value) => {
                        const next = value[0] as UsagePeriod | undefined
                        if (next && next !== period) {
                            setPeriod(next)
                        }
                    }}
                    aria-label="Usage period"
                >
                    {PERIOD_OPTIONS.map((option) => (
                        <ToggleGroupItem
                            key={option.value}
                            value={option.value}
                            disabled={usageLoading}
                            data-attr={`warehouse-usage-period-${option.value}`}
                        >
                            {option.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
            {usageFailed ? (
                <WarehouseResourceError
                    title="Couldn't load usage"
                    onRetry={retryUsage}
                    data-attr="warehouse-usage-retry"
                />
            ) : !usage ? (
                <Skeleton className="h-64 w-full" />
            ) : (
                <div className={usageLoading ? 'flex flex-col gap-4 opacity-60' : 'flex flex-col gap-4'}>
                    <WarehouseUsageTiles />
                    <WarehouseUsageCharts />
                    <WarehouseUsageBreakdown />
                </div>
            )}
            <WarehouseSpendControls />
        </>
    )
}

export function WarehouseUsageScene(): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WarehouseUsage].name}
                    description={sceneConfigurations[Scene.WarehouseUsage].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-usage flex flex-col gap-4">
                    <WarehouseUsageContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
