import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessDenied } from 'lib/components/AccessDenied'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, DataWarehouseSavedQuery } from '~/types'

import { ViewsTab } from '../data-warehouse/scene/ViewsTab'
import { DagsTab } from './DagsTab'
import { ModelsSceneTab, modelsSceneLogic } from './modelsSceneLogic'

export const scene: SceneExport = {
    component: ModelsScene,
    logic: modelsSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
}

export function ModelsScene(): JSX.Element {
    const { savedQueryIdToNodeId, currentTab } = useValues(modelsSceneLogic)
    const { setCurrentTab } = useActions(modelsSceneLogic)

    const getViewUrl = useCallback(
        (view: DataWarehouseSavedQuery): string => {
            const nodeId = savedQueryIdToNodeId[view.id]
            return nodeId ? urls.nodeDetail(nodeId) : urls.sqlEditor({ view_id: view.id })
        },
        [savedQueryIdToNodeId]
    )

    const tabs: LemonTab<ModelsSceneTab>[] = [
        {
            label: 'Views',
            key: 'views',
            content: <ViewsTab getViewUrl={getViewUrl} />,
        },
        {
            label: 'DAGs',
            key: 'dags',
            content: <DagsTab />,
        },
    ]
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
                    currentTab === 'views' ? (
                        <div className="flex gap-2">
                            <Shortcut
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
                                        to={urls.sqlEditor({ source: 'view' })}
                                        size="small"
                                        tooltip="Create view"
                                        data-attr="new-view-button"
                                    >
                                        Create view
                                    </LemonButton>
                                </AccessControlAction>
                            </Shortcut>
                        </div>
                    ) : undefined
                }
            />
            <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} sceneInset />
        </SceneContent>
    )
}
