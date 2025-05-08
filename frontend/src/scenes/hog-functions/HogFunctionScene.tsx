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

import { ActivityScope, Breadcrumb } from '~/types'

import type { hogFunctionSceneLogicType } from './HogFunctionSceneType'
import { HogFunctionSkeleton } from './misc/HogFunctionSkeleton'

export type HogFunctionSceneTab = 'configuration' | 'metrics' | 'logs' | 'testing' | 'history'

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
        breadcrumbs: [
            (s) => [(_, props) => props, s.type],
            ({ templateId, id }, type): Breadcrumb[] => {
                const friendlyType =
                    type === 'destination'
                        ? 'Destination'
                        : type === 'internal_destination'
                        ? 'Notification'
                        : capitalizeFirstLetter(type)

                // TODO: Map URLs as well

                return [
                    {
                        key: Scene.HogFunction,
                        name: friendlyType,
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
                actions.setCurrentTab(search.tab as HogFunctionSceneTab)
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

export function HogFunctionScene(props: HogFunctionConfigurationLogicProps): JSX.Element {
    const { id, templateId } = props
    const { currentTab, loading, loaded } = useValues(hogFunctionSceneLogic(props))
    const { setCurrentTab } = useActions(hogFunctionSceneLogic(props))

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
