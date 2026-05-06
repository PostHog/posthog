import { useValues } from 'kea'
import { useCallback } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessDenied } from 'lib/components/AccessDenied'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, DataWarehouseSavedQuery } from '~/types'

import { ViewsTab } from '../data-warehouse/scene/ViewsTab'
import { modelsSceneLogic } from './modelsSceneLogic'

export const scene: SceneExport = {
    component: ModelsScene,
    logic: modelsSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
}

export function ModelsScene(): JSX.Element {
    const { savedQueryIdToNodeId } = useValues(modelsSceneLogic)

    const getViewUrl = useCallback(
        (view: DataWarehouseSavedQuery): string => {
            const nodeId = savedQueryIdToNodeId[view.id]
            return nodeId ? urls.nodeDetail(nodeId) : urls.sqlEditor({ view_id: view.id })
        },
        [savedQueryIdToNodeId]
    )

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so this page isn't available." />
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Models].name}
                description={sceneConfigurations[Scene.Models].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Models].iconType || 'default_icon_type',
                }}
                actions={
                    <div className="flex gap-2">
                        <AppShortcut
                            name="NewModel"
                            keybind={[keyBinds.new]}
                            intent="New view"
                            interaction="click"
                            scope={Scene.Models}
                        >
                            <AccessControlAction
                                resourceType={AccessControlResourceType.WarehouseObjects}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="primary"
                                    to={urls.sqlEditor()}
                                    size="small"
                                    tooltip="Create view"
                                    data-attr="new-view-button"
                                >
                                    Create view
                                </LemonButton>
                            </AccessControlAction>
                        </AppShortcut>
                    </div>
                }
            />
            <ViewsTab getViewUrl={getViewUrl} />
        </SceneContent>
    )
}
