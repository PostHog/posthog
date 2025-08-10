import { actions, kea, key, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { PipelineNodeLogs } from 'scenes/pipeline/PipelineNodeLogs'
import { PipelineNodeMetrics } from 'scenes/pipeline/PipelineNodeMetrics'
import { PipelinePluginConfiguration } from 'scenes/pipeline/PipelinePluginConfiguration'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, Breadcrumb, PipelineStage } from '~/types'

import type { legacyPluginSceneLogicType } from './LegacyPluginSceneType'

const LEGACY_PLUGIN_SCENE_TABS = ['configuration', 'metrics', 'logs', 'history'] as const
export type LegacyPluginSceneTab = (typeof LEGACY_PLUGIN_SCENE_TABS)[number]

export interface LegacyPluginSceneLogicProps {
    id: string
}

export const legacyPluginSceneLogic = kea<legacyPluginSceneLogicType>([
    props({} as LegacyPluginSceneLogicProps),
    key(({ id }: LegacyPluginSceneLogicProps) => id ?? 'new'),
    path((key) => ['scenes', 'data-pipelines', 'legacy-plugins', 'legacyPluginSceneLogic', key]),
    actions({
        setCurrentTab: (tab: LegacyPluginSceneTab) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            'configuration' as LegacyPluginSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.DataPipelines,
                        name: 'Data pipelines',
                        path: urls.dataPipelines(),
                    },
                    {
                        key: [Scene.DataPipelines, 'destinations'],
                        name: 'Destinations',
                        path: urls.dataPipelines('destinations'),
                    },

                    {
                        key: Scene.LegacyPlugin,
                        name: 'Plugin destination (deprecated)',
                    },
                ]
            },
        ],
    }),
    actionToUrl(({ values }) => ({
        setCurrentTab: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    tab: values.currentTab,
                },
                router.values.hashParams,
            ]
        },
    })),
    urlToAction(({ actions, values }) => {
        const reactToTabChange = (_: any, search: Record<string, string>): void => {
            const possibleTab = (search.tab ?? 'configuration') as LegacyPluginSceneTab

            const tab = LEGACY_PLUGIN_SCENE_TABS.includes(possibleTab) ? possibleTab : 'configuration'
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab)
            }
        }

        return {
            // All possible routes for this scene need to be listed here
            [urls.legacyPlugin(':id')]: reactToTabChange,
        }
    }),
])

export const scene: SceneExport = {
    component: LegacyPluginScene,
    logic: legacyPluginSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof legacyPluginSceneLogic)['props'] => ({
        id,
    }),
}

export function LegacyPluginScene(): JSX.Element {
    const { currentTab, logicProps } = useValues(legacyPluginSceneLogic)
    const { setCurrentTab } = useActions(legacyPluginSceneLogic)

    const { id } = logicProps

    const pluginConfigId = parseInt(id)

    const tabs: (LemonTab<LegacyPluginSceneTab> | null)[] = [
        {
            label: 'Configuration',
            key: 'configuration',
            content: <PipelinePluginConfiguration stage={PipelineStage.Destination} pluginConfigId={pluginConfigId} />,
        },
        {
            label: 'Metrics',
            key: 'metrics',
            content: <PipelineNodeMetrics id={pluginConfigId} />,
        },
        {
            label: 'Logs',
            key: 'logs',
            content: <PipelineNodeLogs id={pluginConfigId} stage={PipelineStage.Destination} />,
        },
        {
            label: 'History',
            key: 'history',
            content: <ActivityLog id={id} scope={ActivityScope.PLUGIN} />,
        },
    ]

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} />
}
