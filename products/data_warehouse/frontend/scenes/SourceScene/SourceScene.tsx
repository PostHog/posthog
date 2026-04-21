import {
    actions,
    BuiltLogic,
    kea,
    key,
    LogicWrapper,
    path,
    props,
    reducers,
    selectors,
    useActions,
    useValues,
} from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { DataPipelinesSelfManagedSource } from 'scenes/data-pipelines/DataPipelinesSelfManagedSource'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb, ExternalDataSource } from '~/types'

import { cleanSourceId, isSelfManagedSourceId } from 'products/data_warehouse/frontend/utils'

import type { sourceSceneLogicType } from './SourceSceneType'
import { ConfigurationTab } from './tabs/ConfigurationTab'
import { SchemasTab } from './tabs/SchemasTab'
import { sourceSettingsLogic } from './tabs/sourceSettingsLogic'
import { SyncsTab } from './tabs/SyncsTab'
import { WebhookTab } from './tabs/WebhookTab'

const SOURCE_SCENE_TABS = ['schemas', 'syncs', 'configuration', 'webhook'] as const
export type SourceSceneTab = (typeof SOURCE_SCENE_TABS)[number]

export interface SourceSceneProps {
    id: string
    tabId?: string
}

export function getDefaultDataWarehouseSourceSceneTab(id?: string): SourceSceneTab {
    return id && isSelfManagedSourceId(id) ? 'configuration' : 'schemas'
}

export function isManagedSourceSceneId(id: string): boolean {
    return !isSelfManagedSourceId(id)
}

export function shouldShowManagedSourceSyncsTab(
    source: Pick<ExternalDataSource, 'access_method'> | null | undefined,
    isDirectQueryEnabled: boolean
): boolean {
    return !!source && !(isDirectQueryEnabled && source.access_method === 'direct')
}

export const sourceSceneLogic = kea<sourceSceneLogicType>([
    props({} as SourceSceneProps),
    key(({ id, tabId }: SourceSceneProps) => (tabId ? `${id}-${tabId}` : id)),
    path((key) => ['products', 'dataWarehouse', 'sourceSceneLogic', key]),
    actions({
        setCurrentTab: (tab: SourceSceneTab) => ({ tab }),
        setBreadcrumbName: (name: string) => ({ name }),
        _setCurrentTab: (tab: SourceSceneTab) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            'schemas' as SourceSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
                // dont trigger actionToUrl
                _setCurrentTab: (_, { tab }) => tab,
            },
        ],
        breadcrumbName: [
            'Source' as string,
            {
                setBreadcrumbName: (_, { name }) => name,
            },
        ],
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            (s) => [s.breadcrumbName],
            (breadcrumbName): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Sources,
                        name: 'Sources',
                        path: urls.sources(),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: Scene.DataWarehouseSource,
                        name: breadcrumbName,
                        iconType: 'data_pipeline',
                    },
                ]
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [(_, props) => props],
            (props): SidePanelSceneContext | null => {
                const id = cleanSourceId(props.id)
                return id
                    ? {
                          activity_scope: ActivityScope.EXTERNAL_DATA_SOURCE,
                          activity_item_id: id,
                          // Only managed sources have access control, self-managed sources do not
                          ...(isManagedSourceSceneId(props.id)
                              ? {
                                    access_control_resource: 'external_data_source',
                                    access_control_resource_id: id,
                                }
                              : {}),
                      }
                    : null
            },
        ],
    }),
    actionToUrl(({ props, values }) => ({
        setCurrentTab: () => {
            return urls.dataWarehouseSource(props.id, values.currentTab)
        },
    })),
    urlToAction(({ actions, values }) => {
        return {
            [urls.dataWarehouseSource(':id', ':tab' as any)]: (params): void => {
                const defaultTab = getDefaultDataWarehouseSourceSceneTab(params.id)
                let possibleTab = (params.tab ?? defaultTab) as SourceSceneTab

                if (params.id && isSelfManagedSourceId(params.id)) {
                    possibleTab = 'configuration' // This only has one tab
                }

                const tab = SOURCE_SCENE_TABS.includes(possibleTab) ? possibleTab : defaultTab
                if (tab !== values.currentTab) {
                    actions._setCurrentTab(tab)
                }
            },
        }
    }),
])

export const scene: SceneExport<(typeof sourceSceneLogic)['props']> = {
    component: SourceScene,
    logic: sourceSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function SourceScene({ id, tabId }: SourceSceneProps): JSX.Element {
    const logic = sourceSceneLogic({ id, tabId })
    const { currentTab, breadcrumbName } = useValues(logic)
    const { setCurrentTab } = useActions(logic)

    if (!id) {
        return <NotFound object="Data warehouse source" />
    }

    const sourceId = cleanSourceId(id)
    const isSelfManagedSource = isSelfManagedSourceId(id)

    return (
        <SceneContent>
            <SceneTitleSection
                name={breadcrumbName}
                resourceType={{ type: 'data_pipeline' }}
                isLoading={breadcrumbName === 'Source'}
            />
            {isManagedSourceSceneId(id) ? (
                <ManagedSourceTabs
                    sourceId={sourceId}
                    currentTab={currentTab}
                    setCurrentTab={setCurrentTab}
                    attachTo={logic}
                    tabId={tabId}
                />
            ) : (
                <LemonTabs
                    activeKey={isSelfManagedSource ? 'configuration' : currentTab}
                    tabs={[
                        {
                            label: 'Configuration',
                            key: 'configuration',
                            content: <DataPipelinesSelfManagedSource id={sourceId} />,
                        },
                    ]}
                    onChange={setCurrentTab}
                    sceneInset
                />
            )}
        </SceneContent>
    )
}

function ManagedSourceTabs({
    sourceId,
    currentTab,
    setCurrentTab,
    attachTo,
    tabId,
}: {
    sourceId: string
    currentTab: SourceSceneTab
    setCurrentTab: (tab: SourceSceneTab) => void
    attachTo: BuiltLogic | LogicWrapper
    tabId?: string
}): JSX.Element {
    const settingsLogic = sourceSettingsLogic({ id: sourceId, availableSources: {} })
    const { featureFlags } = useValues(featureFlagLogic)
    const { source } = useValues(settingsLogic)

    useAttachedLogic(settingsLogic, attachTo)

    const showSyncsTab = shouldShowManagedSourceSyncsTab(
        source,
        !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]
    )
    const showWebhookTab = !!featureFlags[FEATURE_FLAGS.WAREHOUSE_SOURCE_WEBHOOKS] && !!source?.supports_webhooks

    useEffect(() => {
        if (!showSyncsTab && currentTab === 'syncs') {
            setCurrentTab('schemas')
        }
        if (!showWebhookTab && currentTab === 'webhook') {
            setCurrentTab('schemas')
        }
    }, [showSyncsTab, showWebhookTab, currentTab, setCurrentTab])

    const tabs: LemonTab<SourceSceneTab>[] = [
        {
            label: 'Schemas',
            key: 'schemas',
            content: <SchemasTab id={sourceId} />,
        },
        {
            label: 'Configuration',
            key: 'configuration',
            content: <ConfigurationTab id={sourceId} />,
        },
    ]

    if (showSyncsTab) {
        tabs.splice(1, 0, {
            label: 'Syncs',
            key: 'syncs',
            content: <SyncsTab id={sourceId} />,
        })
    }

    if (showWebhookTab) {
        tabs.push({
            label: 'Webhook',
            key: 'webhook',
            content: <WebhookTab id={sourceId} tabId={tabId} />,
        })
    }

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} sceneInset />
}
