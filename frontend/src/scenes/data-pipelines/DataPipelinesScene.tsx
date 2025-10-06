import { actions, kea, listeners, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { router, urlToAction } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ActivityScope, Breadcrumb } from '~/types'

import { DataPipelinesHogFunctions } from './DataPipelinesHogFunctions'
import { DataPipelinesOverview } from './DataPipelinesOverview'
import type { dataPipelinesSceneLogicType } from './DataPipelinesSceneType'
import { DataPipelinesSources } from './DataPipelinesSources'

const DATA_PIPELINES_SCENE_TABS = [
    'overview',
    'sources',
    'transformations',
    'destinations',
    'site_apps',
    'history',
] as const
export type DataPipelinesSceneTab = (typeof DATA_PIPELINES_SCENE_TABS)[number]

export type DataPipelinesSceneProps = {
    kind: DataPipelinesSceneTab
}

export const dataPipelinesSceneLogic = kea<dataPipelinesSceneLogicType>([
    props({} as DataPipelinesSceneProps),
    path(() => ['scenes', 'data-pipelines', 'dataPipelinesSceneLogic']),
    actions({
        setCurrentTab: (tab: DataPipelinesSceneTab) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            'overview' as DataPipelinesSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            () => [(_, props) => props],
            ({ kind }): Breadcrumb[] => {
                return [
                    {
                        key: Scene.DataPipelines,
                        name: 'Data pipelines',
                        path: urls.dataPipelines(),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: [Scene.DataPipelines, kind],
                        name: capitalizeFirstLetter(kind.replaceAll('_', ' ')),
                        iconType: 'data_pipeline',
                    },
                ]
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.HOG_FUNCTION,
            }),
        ],
    }),
    listeners({
        setCurrentTab: ({ tab }) => {
            router.actions.push(urls.dataPipelines(tab))
        },
    }),
    urlToAction(({ actions, values }) => {
        return {
            // All possible routes for this scene need to be listed here
            [urls.dataPipelines(':kind' as any)]: ({ kind }) => {
                const possibleTab: DataPipelinesSceneTab = (kind as DataPipelinesSceneTab) ?? 'overview'

                const tab = DATA_PIPELINES_SCENE_TABS.includes(possibleTab) ? possibleTab : 'overview'
                if (tab !== values.currentTab) {
                    actions.setCurrentTab(tab)
                }
            },
        }
    }),
])

export const scene: SceneExport = {
    component: DataPipelinesScene,
    logic: dataPipelinesSceneLogic,
    paramsToProps: ({ params: { kind } }): (typeof dataPipelinesSceneLogic)['props'] => ({
        kind,
    }),
}

function DataPipelineTabs({ action }: { action: JSX.Element }): JSX.Element {
    const { currentTab } = useValues(dataPipelinesSceneLogic)
    const { setCurrentTab } = useActions(dataPipelinesSceneLogic)
    const tabs: LemonTab<DataPipelinesSceneTab>[] = [
        {
            label: 'Overview',
            key: 'overview',
            content: <DataPipelinesOverview />,
        },
        {
            label: 'Sources',
            key: 'sources',
            content: <DataPipelinesSources action={action} />,
        },
        {
            label: 'Transformations',
            key: 'transformations',
            content: <DataPipelinesHogFunctions kind="transformation" action={action} />,
        },
        {
            label: 'Destinations',
            key: 'destinations',
            content: (
                <DataPipelinesHogFunctions kind="destination" additionalKinds={['site_destination']} action={action} />
            ),
        },
        {
            label: 'Apps',
            key: 'site_apps',
            content: <DataPipelinesHogFunctions kind="site_app" action={action} />,
        },
        {
            label: 'History',
            key: 'history',
            content: <ActivityLog scope={[ActivityScope.HOG_FUNCTION]} />,
        },
    ]

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} sceneInset />
}

export function DataPipelinesScene(): JSX.Element {
    const { currentTab } = useValues(dataPipelinesSceneLogic)

    const menuItems: LemonMenuItems = [
        {
            label: 'Source',
            to: urls.dataPipelinesNew('source'),
            'data-attr': 'data-warehouse-data-pipelines-overview-new-source',
        },
        { label: 'Transformation', to: urls.dataPipelinesNew('transformation') },
        { label: 'Destination', to: urls.dataPipelinesNew('destination') },
    ]

    const SceneAction = (): JSX.Element => {
        if (currentTab === 'overview') {
            return (
                <LemonMenu items={menuItems}>
                    <LemonButton data-attr="new-pipeline-button" icon={<IconPlusSmall />} size="small" type="primary">
                        New
                    </LemonButton>
                </LemonMenu>
            )
        }
        if (currentTab === 'sources') {
            return (
                <LemonButton to={urls.dataPipelinesNew('source')} type="primary" icon={<IconPlusSmall />} size="small">
                    New source
                </LemonButton>
            )
        }
        if (currentTab === 'transformations') {
            return (
                <LemonButton
                    to={urls.dataPipelinesNew('transformation')}
                    type="primary"
                    icon={<IconPlusSmall />}
                    size="small"
                >
                    New transformation
                </LemonButton>
            )
        }
        if (currentTab === 'destinations') {
            return (
                <LemonButton
                    to={urls.dataPipelinesNew('destination')}
                    type="primary"
                    icon={<IconPlusSmall />}
                    size="small"
                >
                    New destination
                </LemonButton>
            )
        }
        return (
            <LemonButton to={urls.dataPipelinesNew('site_app')} type="primary" icon={<IconPlusSmall />} size="small">
                New app
            </LemonButton>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Data pipelines"
                resourceType={{
                    type: 'data_pipeline',
                }}
                actions={<SceneAction />}
            />
            <SceneDivider />
            <DataPipelineTabs action={<SceneAction />} />
        </SceneContent>
    )
}
