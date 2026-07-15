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

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
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
import { ActivityScope, Breadcrumb, ExternalDataSource, ExternalDataSourceApiVersionDeprecation } from '~/types'

import { cleanSourceId, isSelfManagedSourceId } from 'products/data_warehouse/frontend/utils'

import type { sourceSceneLogicType } from './SourceSceneType'
import { ConfigurationTab } from './tabs/ConfigurationTab'
import { MetricsTab } from './tabs/MetricsTab'
import { SchemasTab } from './tabs/SchemasTab'
import { sourceSettingsLogic } from './tabs/sourceSettingsLogic'
import { SyncsTab } from './tabs/SyncsTab'
import { WebhookTab } from './tabs/WebhookTab'

const SOURCE_SCENE_TABS = ['schemas', 'syncs', 'metrics', 'configuration', 'webhook', 'history'] as const
export type SourceSceneTab = (typeof SOURCE_SCENE_TABS)[number]

export interface SourceSceneProps {
    id: string
}

export function getDefaultDataWarehouseSourceSceneTab(id?: string): SourceSceneTab {
    return id && isSelfManagedSourceId(id) ? 'configuration' : 'schemas'
}

export function isManagedSourceSceneId(id: string): boolean {
    return !isSelfManagedSourceId(id)
}

export function shouldShowManagedSourceSyncsTab(
    source: Pick<ExternalDataSource, 'access_method'> | null | undefined
): boolean {
    return !!source && source.access_method !== 'direct'
}

export const sourceSceneLogic = kea<sourceSceneLogicType>([
    props({} as SourceSceneProps),
    key(({ id }: SourceSceneProps) => id),
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

export function SourceScene({ id }: SourceSceneProps): JSX.Element {
    const logic = sourceSceneLogic({ id })
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
}: {
    sourceId: string
    currentTab: SourceSceneTab
    setCurrentTab: (tab: SourceSceneTab) => void
    attachTo: BuiltLogic | LogicWrapper
}): JSX.Element {
    const settingsLogic = sourceSettingsLogic({ id: sourceId, availableSources: {} })
    const { featureFlags } = useValues(featureFlagLogic)
    const { source, sourceLoading } = useValues(settingsLogic)

    useAttachedLogic(settingsLogic, attachTo)

    const showSyncsTab = shouldShowManagedSourceSyncsTab(source)
    const showWebhookTab = !!source?.supports_webhooks
    const showMetricsTab = !!featureFlags[FEATURE_FLAGS.DWH_SOURCE_METRICS]

    useEffect(() => {
        // Wait until the source has loaded before deciding a tab is unavailable.
        // While `source` is null, showSyncsTab/showWebhookTab are false, so a tab
        // selected via URL (e.g. "syncs") would get bounced to "schemas" and push
        // a bogus history entry over the URL the user actually navigated to.
        if (!source) {
            return
        }
        if (!showSyncsTab && currentTab === 'syncs') {
            setCurrentTab('schemas')
        }
        if (!showWebhookTab && currentTab === 'webhook') {
            setCurrentTab('schemas')
        }
        if (!showMetricsTab && currentTab === 'metrics') {
            setCurrentTab('schemas')
        }
    }, [source, showSyncsTab, showWebhookTab, showMetricsTab, currentTab, setCurrentTab])

    if (sourceLoading && !source) {
        return <LemonSkeleton className="w-full h-12" />
    }

    const tabs: LemonTab<SourceSceneTab>[] = [
        { label: 'Schemas', key: 'schemas', content: <SchemasTab id={sourceId} /> },
    ]

    if (showSyncsTab) {
        tabs.push({ label: 'Syncs', key: 'syncs', content: <SyncsTab id={sourceId} /> })
    }

    if (showMetricsTab) {
        tabs.push({ label: 'Metrics', key: 'metrics', content: <MetricsTab id={sourceId} /> })
    }

    tabs.push({ label: 'Configuration', key: 'configuration', content: <ConfigurationTab id={sourceId} /> })

    if (showWebhookTab) {
        tabs.push({
            label: 'Webhook',
            key: 'webhook',
            content: <WebhookTab id={sourceId} />,
        })
    }

    tabs.push({
        label: 'History',
        key: 'history',
        content: <ActivityLog id={sourceId} scope={ActivityScope.EXTERNAL_DATA_SOURCE} />,
    })

    return (
        <>
            {source?.api_version_deprecation && (
                <ApiVersionDeprecationBanner
                    sourceType={source.source_type}
                    deprecation={source.api_version_deprecation}
                />
            )}
            <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} sceneInset />
        </>
    )
}

export function ApiVersionDeprecationBanner({
    sourceType,
    deprecation,
    subject = 'This source',
    cta,
}: {
    sourceType: string
    deprecation: ExternalDataSourceApiVersionDeprecation
    subject?: string
    cta?: string
}): JSX.Element {
    return (
        <LemonBanner type="warning">
            {subject} syncs using {sourceType} API version {deprecation.version}, which the vendor has deprecated
            {deprecation.sunset_at ? ` and will stop serving on ${dayjs(deprecation.sunset_at).format('LL')}` : ''}.{' '}
            {cta ??
                `Contact PostHog support to migrate this source to version ${deprecation.default_version} before syncs stop working.`}
        </LemonBanner>
    )
}
