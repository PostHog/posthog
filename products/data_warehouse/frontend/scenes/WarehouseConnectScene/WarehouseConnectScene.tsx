import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehouseConnectDetails } from './WarehouseConnectDetails'
import { WarehouseConnectSnippets } from './WarehouseConnectSnippets'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export const scene: SceneExport = {
    component: WarehouseConnectScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

function WarehouseConnectContent(): JSX.Element {
    const { consoleState, trinoConnection, teamSchemaName } = useValues(warehouseConsoleLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page="connect" />
    }
    if (!trinoConnection) {
        return <Text variant="muted">Connection details are temporarily unavailable. Refresh to try again.</Text>
    }
    return (
        <>
            <WarehouseConnectDetails connection={trinoConnection} schemaName={teamSchemaName} />
            <WarehouseConnectSnippets connection={trinoConnection} schemaName={teamSchemaName} />
        </>
    )
}

export function WarehouseConnectScene(): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WarehouseConnect].name}
                    description={sceneConfigurations[Scene.WarehouseConnect].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-connect flex flex-col gap-4">
                    <WarehouseConnectContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
