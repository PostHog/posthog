import { actions, kea, listeners, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { router, urlToAction } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

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
                    },
                    {
                        key: [Scene.DataPipelines, kind],
                        name: capitalizeFirstLetter(kind.replaceAll('_', ' ')),
                    },
                ]
            },
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
            [urls.dataPipelines(':kind')]: ({ kind }) => {
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

export function DataPipelinesScene(): JSX.Element {
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
            content: <DataPipelinesSources />,
        },
        {
            label: 'Transformations',
            key: 'transformations',
            content: <DataPipelinesHogFunctions kind="transformation" />,
        },
        {
            label: 'Destinations',
            key: 'destinations',
            content: <DataPipelinesHogFunctions kind="destination" additionalKinds={['site_destination']} />,
        },
        {
            label: 'Apps',
            key: 'site_apps',
            content: <DataPipelinesHogFunctions kind="site_app" />,
        },
        {
            label: 'History',
            key: 'history',
            content: <ActivityLog scope={[ActivityScope.HOG_FUNCTION]} />,
        },
    ]

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} />
}
