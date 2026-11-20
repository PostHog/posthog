import { useValues } from 'kea'
import posthog from 'posthog-js'

import { Button, Card, CardContent, CardHeader, CardTitle, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

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
            <Card>
                <CardHeader>
                    <CardTitle>Password</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                    <Text size="sm">
                        Your password comes from warehouse setup, where it is shown once. If you lost it, reset it on
                        the Access page. Admins can also create project logins there.
                    </Text>
                    <div>
                        <Button
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.warehouseAccess()} />}
                            onClick={() => posthog.capture('warehouse connect access clicked')}
                            data-attr="warehouse-connect-open-access"
                        >
                            Open Access
                        </Button>
                    </div>
                </CardContent>
            </Card>
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
