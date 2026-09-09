import { useValues } from 'kea'
import { useCallback } from 'react'

import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessDenied } from 'lib/components/AccessDenied'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, DataWarehouseSavedQuery } from '~/types'

import { DataQualityOverview } from 'products/data_quality/frontend/overview/DataQualityOverview'

import { ViewsTab } from '../data-warehouse/scene/ViewsTab'
import { ModelsSceneTab, modelsSceneLogic } from './modelsSceneLogic'
import { ModelsLineageTab } from './tabs/ModelsLineageTab'
import { ModelsOverviewTab } from './tabs/ModelsOverviewTab'

export const scene: SceneExport = {
    component: ModelsScene,
    logic: modelsSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
}

export function ModelsScene(): JSX.Element {
    const { savedQueryIdToNodeId, activeTab, dataQualityTabEnabled } = useValues(modelsSceneLogic)

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

    const tabs: LemonTab<ModelsSceneTab>[] = [
        {
            key: 'overview',
            label: 'Overview',
            link: urls.models(),
            content: <ModelsOverviewTab />,
            'data-attr': 'models-tab-overview',
        },
        {
            key: 'models',
            label: 'Models',
            link: urls.models('models'),
            content: <ViewsTab getViewUrl={getViewUrl} />,
            'data-attr': 'models-tab-models',
        },
        {
            key: 'lineage',
            label: 'Lineage',
            link: urls.models('lineage'),
            content: <ModelsLineageTab />,
            'data-attr': 'models-tab-lineage',
        },
        ...(dataQualityTabEnabled
            ? [
                  {
                      key: 'data-quality' as const,
                      label: 'Data quality',
                      link: urls.models('data-quality'),
                      content: <DataQualityOverview />,
                      'data-attr': 'models-tab-data-quality',
                  },
              ]
            : []),
    ]

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
                }
            />
            <LemonTabs activeKey={activeTab} tabs={tabs} sceneInset />
        </SceneContent>
    )
}
