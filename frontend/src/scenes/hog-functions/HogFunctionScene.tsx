import { actions, connect, kea, key, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { HogFunctionConfiguration } from 'scenes/hog-functions/configuration/HogFunctionConfiguration'
import {
    hogFunctionConfigurationLogic,
    HogFunctionConfigurationLogicProps,
} from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { HogFunctionLogs } from 'scenes/hog-functions/logs/HogFunctionLogs'
import { HogFunctionMetrics } from 'scenes/hog-functions/metrics/HogFunctionMetrics'
import { HogFunctionTesting } from 'scenes/hog-functions/testing/HogFunctionTesting'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    ActivityScope,
    Breadcrumb,
    CyclotronJobFilterPropertyFilter,
    HogFunctionType,
    HogFunctionTypeType,
    PipelineTab,
} from '~/types'

import type { hogFunctionSceneLogicType } from './HogFunctionSceneType'
import { HogFunctionSkeleton } from './misc/HogFunctionSkeleton'

const HOG_FUNCTION_SCENE_TABS = ['configuration', 'metrics', 'logs', 'testing', 'history'] as const
export type HogFunctionSceneTab = (typeof HOG_FUNCTION_SCENE_TABS)[number]

const DataPipelinesSceneMapping: Partial<Record<HogFunctionTypeType, PipelineTab>> = {
    transformation: PipelineTab.Transformations,
    destination: PipelineTab.Destinations,
    site_destination: PipelineTab.Destinations,
    site_app: PipelineTab.SiteApps,
    source_webhook: PipelineTab.Sources,
}

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
        alertId: [
            (s) => [s.configuration],
            (configuration: HogFunctionType | null): string | undefined => {
                if (!configuration?.filters?.properties) {
                    return undefined
                }
                const alertIdProp = configuration.filters.properties.find(
                    (p: CyclotronJobFilterPropertyFilter) => p.key === 'alert_id'
                )
                const value = alertIdProp?.value
                return value ? String(value) : undefined
            },
        ],
        breadcrumbs: [
            (s) => [s.type, s.loading, s.configuration, s.alertId],
            (
                type: HogFunctionTypeType,
                loading: boolean,
                configuration: HogFunctionType | null,
                alertId: string | undefined
            ): Breadcrumb[] => {
                if (loading) {
                    return [
                        {
                            key: Scene.HogFunction,
                            name: 'Loading...',
                        },
                    ]
                }

                const finalCrumb: Breadcrumb = {
                    key: Scene.HogFunction,
                    name: configuration?.name || '(Untitled)',
                }

                if (type === 'internal_destination' && alertId) {
                    return [
                        {
                            key: Scene.Insight,
                            name: 'Insight',
                            path: urls.alerts(),
                        },
                        {
                            key: 'alert',
                            name: 'Alert',
                            path: urls.alert(alertId),
                        },
                        finalCrumb,
                    ]
                }

                const pipelineTab = DataPipelinesSceneMapping[type]

                if (pipelineTab) {
                    return [
                        {
                            key: Scene.Pipeline,
                            name: 'Data pipelines',
                            path: urls.pipeline(PipelineTab.Overview),
                        },
                        {
                            key: Scene.HogFunction,
                            name: `${capitalizeFirstLetter(type).replace('_', ' ')}s`,
                            path: urls.pipeline(pipelineTab),
                        },
                        finalCrumb,
                    ]
                }

                if (type === 'internal_destination') {
                    // Returns a Scene that is closest to the element based on the configuration.
                    // This is used to help the HogFunctionScene render correct breadcrumbs and redirections
                    if (configuration?.filters?.events?.some((e) => e.id.includes('error_tracking'))) {
                        // Error tracking scene
                        return [
                            {
                                key: Scene.ErrorTracking,
                                name: 'Error tracking',
                                path: urls.errorTracking(),
                            },
                            {
                                key: Scene.HogFunction,
                                name: 'Alerts',
                                path: urls.errorTrackingConfiguration() + '#selectedSetting=error-tracking-alerting',
                            },
                            finalCrumb,
                        ]
                    }

                    return [
                        {
                            key: Scene.HogFunction,
                            name: 'Notifications',
                        },
                        finalCrumb,
                    ]
                }
                return [
                    {
                        key: Scene.HogFunction,
                        name: 'Function',
                    },
                    finalCrumb,
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
            const possibleTab = (search.tab ?? 'configuration') as HogFunctionSceneTab

            const tab = HOG_FUNCTION_SCENE_TABS.includes(possibleTab) ? possibleTab : 'configuration'
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab)
            }
        }

        return {
            // All possible routes for this scene need to be listed here
            [urls.hogFunction(':id')]: reactToTabChange,
            [urls.errorTrackingAlert(':id')]: reactToTabChange,
        }
    }),
])

export const scene: SceneExport = {
    component: HogFunctionScene,
    logic: hogFunctionSceneLogic,
    paramsToProps: ({ params: { id, templateId } }): (typeof hogFunctionSceneLogic)['props'] => ({ id, templateId }),
}

export function HogFunctionScene(): JSX.Element {
    const { currentTab, loading, loaded, logicProps, type } = useValues(hogFunctionSceneLogic)
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

    const tabs: (LemonTab<HogFunctionSceneTab> | null)[] = [
        {
            label: 'Configuration',
            key: 'configuration',
            content: <HogFunctionConfiguration id={id} />,
        },

        type === 'site_app' || type === 'site_destination'
            ? null
            : {
                  label: 'Metrics',
                  key: 'metrics',
                  content: <HogFunctionMetrics id={id} />,
              },
        type === 'site_app' || type === 'site_destination'
            ? null
            : {
                  label: 'Logs',
                  key: 'logs',
                  content: <HogFunctionLogs hogFunctionId={id} />,
              },
        type === 'site_app' || type === 'site_destination'
            ? null
            : {
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
