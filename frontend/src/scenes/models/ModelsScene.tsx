import { useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useCallback } from 'react'

import { LemonButton, LemonTab, LemonTabs, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessDenied } from 'lib/components/AccessDenied'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'
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
import { ModelsGraphTab } from './tabs/ModelsGraphTab'
import { ModelsRunsTab } from './tabs/ModelsRunsTab'

export const scene: SceneExport = {
    component: ModelsScene,
    logic: modelsSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
}

const NAMES_IN_TOOLTIP = 5

function namesTooltip(names: string[]): string {
    const shown = names.slice(0, NAMES_IN_TOOLTIP).join(', ')
    const rest = names.length - NAMES_IN_TOOLTIP
    return rest > 0 ? `${shown} and ${rest} more` : shown
}

function ModelsHealthStrip(): JSX.Element | null {
    const { failingNodes, suspendedViews } = useValues(modelsSceneLogic)

    if (failingNodes.length === 0 && suspendedViews.length === 0) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-attr="models-health-strip">
            {failingNodes.length > 0 && (
                <Tooltip title={namesTooltip(failingNodes.map((node) => node.name))}>
                    <Link to={combineUrl(urls.models('runs'), { status: 'Failed' }).url}>
                        <LemonTag type="danger">{pluralize(failingNodes.length, 'model')} failing</LemonTag>
                    </Link>
                </Tooltip>
            )}
            {suspendedViews.length > 0 && (
                <Tooltip title={namesTooltip(suspendedViews.map((view) => view.name))}>
                    <LemonTag type="warning">{pluralize(suspendedViews.length, 'model')} suspended</LemonTag>
                </Tooltip>
            )}
            {suspendedViews.length > 0 && (
                <span className="text-muted">
                    Scheduled runs skip suspended models. Open a model to see the error and resume it.
                </span>
            )}
        </div>
    )
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
            key: 'models',
            label: 'Models',
            link: urls.models(),
            content: <ViewsTab getViewUrl={getViewUrl} />,
            'data-attr': 'models-tab-models',
        },
        {
            key: 'runs',
            label: 'Runs',
            link: urls.models('runs'),
            content: <ModelsRunsTab />,
            'data-attr': 'models-tab-runs',
        },
        {
            key: 'graph',
            label: 'Graph',
            link: urls.models('graph'),
            content: <ModelsGraphTab />,
            'data-attr': 'models-tab-graph',
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
            <ModelsHealthStrip />
            <LemonTabs activeKey={activeTab} tabs={tabs} sceneInset />
        </SceneContent>
    )
}
