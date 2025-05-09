import { actions, connect, kea, key, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { HogFunctionMetrics } from 'scenes/hog-functions/metrics/HogFunctionMetrics'
import { HogFunctionTesting } from 'scenes/hog-functions/testing/HogFunctionTesting'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import {
    hogFunctionConfigurationLogic,
    HogFunctionConfigurationLogicProps,
} from 'scenes/pipeline/hogfunctions/hogFunctionConfigurationLogic'
import { HogFunctionLogs } from 'scenes/pipeline/hogfunctions/logs/HogFunctionLogs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, Breadcrumb, PipelineTab } from '~/types'

import type { hogFunctionSceneLogicType } from './HogFunctionSceneType'
import { HogFunctionSkeleton } from './misc/HogFunctionSkeleton'

const HOG_FUNCTION_SCENE_TABS = ['configuration', 'metrics', 'logs', 'testing', 'history'] as const
export type HogFunctionSceneTab = (typeof HOG_FUNCTION_SCENE_TABS)[number]

export const hogFunctionSceneLogic = kea<hogFunctionSceneLogicType>([
    props({} as HogFunctionConfigurationLogicProps),
    key(({ id, templateId }: HogFunctionConfigurationLogicProps) => id ?? templateId ?? 'new'),
    path((key) => ['scenes', 'hog-functions', 'hogFunctionSceneLogic', key]),
    connect((props: HogFunctionConfigurationLogicProps) => ({
        values: [hogFunctionConfigurationLogic(props), ['configuration', 'type', 'loading', 'loaded']],
    })),
    actions({
        setCurrentTab: (tab: HogFunctionSceneTab) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            'configuration' as HogFunctionSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            (s) => [(_, props) => props, s.type, s.loading, s.configuration],
            ({ templateId, id }, type, loading, configuration): Breadcrumb[] => {
                if (loading) {
                    return [
                        {
                            key: Scene.HogFunction,
                            name: 'Loading...',
                        },
                        {
                            key: Scene.HogFunction,
                            name: '',
                        },
                    ]
                }

                if (type === 'transformation' || type === 'destination') {
                    return [
                        {
                            key: Scene.Pipeline,
                            name: 'Data pipelines',
                            path: urls.pipeline(PipelineTab.Overview),
                        },
                        {
                            key: Scene.HogFunction,
                            name: `${capitalizeFirstLetter(type)}s`,
                            path: urls.pipeline(
                                type === 'destination' ? PipelineTab.Destinations : PipelineTab.Transformations
                            ),
                        },
                        {
                            key: Scene.HogFunction,
                            name: configuration?.name || '(Untitled)',
                            path: urls.hogFunction(id),
                        },
                    ]
                }

                return [
                    {
                        key: Scene.HogFunction,
                        name: 'Function',
                        path: urls.hogFunction(id),
                    },
                    {
                        key: Scene.HogFunction,
                        path: urls.hogFunction(id),
                        name: templateId ? 'New' : 'Edit',
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
    urlToAction(({ actions }) => ({
        '*': (_, search) => {
            if ('tab' in search) {
                actions.setCurrentTab(
                    HOG_FUNCTION_SCENE_TABS.includes(search.tab as HogFunctionSceneTab)
                        ? (search.tab as HogFunctionSceneTab)
                        : 'configuration'
                )
                return
            }
        },
    })),
])

export const scene: SceneExport = {
    component: HogFunctionScene,
    logic: hogFunctionSceneLogic,
    paramsToProps: ({ params: { id, templateId } }): (typeof hogFunctionSceneLogic)['props'] => ({ id, templateId }),
}

export function HogFunctionScene(): JSX.Element {
    const { currentTab, loading, loaded, logicProps } = useValues(hogFunctionSceneLogic)
    const { setCurrentTab } = useActions(hogFunctionSceneLogic)

    const { id, templateId } = logicProps

    if (loading && !loaded) {
        return (
            <div className="flex flex-col gap-4">
                <LemonSkeleton className="w-full h-12" />
                <HogFunctionSkeleton />
            </div>
        )
    }

    if (!loaded) {
        return <NotFound object="Hog function" />
    }

    if (templateId) {
        return <HogFunctionConfiguration templateId={templateId} />
    }

    if (!id) {
        return <NotFound object="Hog function" />
    }

    const tabs: LemonTab<HogFunctionSceneTab>[] = [
        {
            label: 'Configuration',
            key: 'configuration',
            content: (
                <HogFunctionConfiguration
                    id={id}
                    // displayOptions={{ hideTestingConfiguration: false }}
                />
            ),
        },
        {
            label: 'Metrics',
            key: 'metrics',
            content: <HogFunctionMetrics id={id} />,
        },
        {
            label: 'Logs',
            key: 'logs',
            content: <HogFunctionLogs hogFunctionId={id} />,
        },
        {
            label: 'Testing',
            key: 'testing',
            content: <HogFunctionTesting id={id} />,
        },
        {
            label: 'History',
            key: 'history',
            content: <ActivityLog id={id} scope={ActivityScope.HOG_FUNCTION} />,
        },
    ]

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} />
}
