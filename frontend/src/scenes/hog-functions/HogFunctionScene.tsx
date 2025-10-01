import { BindLogic, actions, connect, kea, key, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { LemonDivider } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { DataPipelinesNewSceneKind } from 'scenes/data-pipelines/DataPipelinesNewScene'
import { DataPipelinesSceneTab } from 'scenes/data-pipelines/DataPipelinesScene'
import { HogFunctionConfiguration } from 'scenes/hog-functions/configuration/HogFunctionConfiguration'
import {
    HogFunctionConfigurationLogicProps,
    hogFunctionConfigurationLogic,
} from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { HogFunctionLogs } from 'scenes/hog-functions/logs/HogFunctionLogs'
import { HogFunctionTesting } from 'scenes/hog-functions/testing/HogFunctionTesting'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ActivityScope,
    Breadcrumb,
    CyclotronJobFilterPropertyFilter,
    HogFunctionType,
    HogFunctionTypeType,
} from '~/types'

import type { hogFunctionSceneLogicType } from './HogFunctionSceneType'
import { HogFunctionIconEditable } from './configuration/HogFunctionIcon'
import {
    HogFunctionConfigurationClearChangesButton,
    HogFunctionConfigurationSaveButton,
} from './configuration/components/HogFunctionConfigurationButtons'
import { HogFunctionMetrics } from './metrics/HogFunctionMetrics'
import { HogFunctionSkeleton } from './misc/HogFunctionSkeleton'

const HOG_FUNCTION_SCENE_TABS = ['configuration', 'metrics', 'logs', 'testing', 'history'] as const
export type HogFunctionSceneTab = (typeof HOG_FUNCTION_SCENE_TABS)[number]

const DataPipelinesSceneMapping: Partial<Record<HogFunctionTypeType, DataPipelinesSceneTab>> = {
    transformation: 'transformations',
    destination: 'destinations',
    site_destination: 'destinations',
    site_app: 'site_apps',
    source_webhook: 'sources',
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
            (s) => [s.type, s.loading, s.configuration, s.alertId, (_, props) => props.id ?? null],
            (
                type: HogFunctionTypeType,
                loading: boolean,
                configuration: HogFunctionType | null,
                alertId: string | undefined,
                id: string | null
            ): Breadcrumb[] => {
                if (loading) {
                    return [
                        {
                            key: Scene.HogFunction,
                            name: 'Loading...',
                            iconType: 'data_pipeline',
                        },
                    ]
                }

                const finalCrumb: Breadcrumb = {
                    key: Scene.HogFunction,
                    name: configuration?.name || '(Untitled)',
                    iconType: 'data_pipeline',
                }

                if (type === 'internal_destination' && alertId) {
                    return [
                        {
                            key: Scene.Insight,
                            name: 'Insight',
                            path: urls.alerts(),
                            iconType: 'data_pipeline',
                        },
                        {
                            key: 'alert',
                            name: 'Alert',
                            path: urls.alert(alertId),
                            iconType: 'data_pipeline',
                        },
                        finalCrumb,
                    ]
                }

                const pipelineTab = DataPipelinesSceneMapping[type]

                if (pipelineTab) {
                    return [
                        {
                            key: Scene.DataPipelines,
                            name: 'Data pipelines',
                            path: urls.dataPipelines('overview'),
                            iconType: 'data_pipeline',
                        },
                        {
                            key: [Scene.DataPipelines, pipelineTab],
                            name: `${capitalizeFirstLetter(type).replace('_', ' ')}s`,
                            path: id
                                ? urls.dataPipelines(pipelineTab)
                                : urls.dataPipelinesNew(type as DataPipelinesNewSceneKind),
                            iconType: 'data_pipeline',
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

export const scene: SceneExport<HogFunctionConfigurationLogicProps> = {
    component: HogFunctionScene,
    logic: hogFunctionSceneLogic,
    paramsToProps: ({ params: { id, templateId }, hashParams }) => {
        return {
            id,
            templateId,
            subTemplateId: hashParams.configuration?.sub_template_id,
        }
    },
}

function HogFunctionHeader(): JSX.Element {
    const { configuration, logicProps, loading, isLegacyPlugin } = useValues(hogFunctionConfigurationLogic)
    const { setConfigurationValue, duplicate, deleteHogFunction } = useActions(hogFunctionConfigurationLogic)

    return (
        <>
            <SceneTitleSection
                name={configuration.name}
                description={configuration.description || ''}
                resourceType={{
                    type: 'data_pipeline',
                    forceIcon: (
                        <span className="ml-2 flex">
                            <HogFunctionIconEditable
                                logicKey={logicProps.id ?? 'new'}
                                src={configuration.icon_url}
                                onChange={(val) => setConfigurationValue('icon_url', val)}
                                size="small"
                            />
                        </span>
                    ),
                }}
                isLoading={loading}
                onNameChange={(value) => setConfigurationValue('name', value)}
                onDescriptionChange={(value) => setConfigurationValue('description', value)}
                canEdit
                actions={
                    <>
                        {!logicProps.templateId && (
                            <>
                                <More
                                    size="small"
                                    overlay={
                                        <>
                                            {!isLegacyPlugin && (
                                                <LemonButton fullWidth onClick={() => duplicate()}>
                                                    Duplicate
                                                </LemonButton>
                                            )}
                                            <LemonDivider />
                                            <LemonButton status="danger" fullWidth onClick={() => deleteHogFunction()}>
                                                Delete
                                            </LemonButton>
                                        </>
                                    }
                                />
                                <LemonDivider vertical />
                            </>
                        )}
                        <HogFunctionConfigurationClearChangesButton />
                        <HogFunctionConfigurationSaveButton />
                    </>
                }
            />
        </>
    )
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

    if (id && !loaded) {
        return <NotFound object="Hog function" />
    }

    if (!templateId && !id) {
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
                  content: <HogFunctionLogs />,
              },
        type === 'site_app' || type === 'site_destination' || type === 'internal_destination'
            ? null
            : {
                  label: 'Testing',
                  key: 'testing',
                  content: <HogFunctionTesting />,
              },
        {
            label: 'History',
            key: 'history',
            content: <ActivityLog id={id} scope={ActivityScope.HOG_FUNCTION} />,
        },
    ]

    return (
        <SceneContent>
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
                <HogFunctionHeader />
                <SceneDivider />
                {templateId ? (
                    <HogFunctionConfiguration templateId={templateId} />
                ) : (
                    <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} sceneInset={true} />
                )}
            </BindLogic>
        </SceneContent>
    )
}
