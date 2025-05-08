import { actions, connect, kea, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { HogFunctionMetrics } from 'scenes/hog-functions/metrics/HogFunctionMetrics'
import { HogFunctionTesting } from 'scenes/hog-functions/testing/HogFunctionTesting'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { hogFunctionConfigurationLogic } from 'scenes/pipeline/hogfunctions/hogFunctionConfigurationLogic'
import { HogFunctionLogs } from 'scenes/pipeline/hogfunctions/logs/HogFunctionLogs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, Breadcrumb } from '~/types'

import type { hogFunctionSceneLogicType } from './HogFunctionSceneType'
export type HogFunctionSceneLogicProps = { id: string }

export type HogFunctionSceneTab = 'configuration' | 'metrics' | 'logs' | 'testing' | 'history'

export const hogFunctionSceneLogic = kea<hogFunctionSceneLogicType>([
    path((key) => ['scenes', 'hog-functions', 'hogFunctionSceneLogic', key]),
    props({} as HogFunctionSceneLogicProps),
    connect(({ id }: HogFunctionSceneLogicProps) => ({
        values: [
            hogFunctionConfigurationLogic({
                id: id,
            }),
            ['configuration'],
        ],
    })),
    actions({
        setCurrentTab: (tab: HogFunctionSceneTab) => ({ tab }),
    }),
    reducers(({}) => ({
        currentTab: [
            'configuration' as HogFunctionSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            (_, p) => [p.id],
            (id): Breadcrumb[] => [
                {
                    key: Scene.HogFunction,
                    name: 'Hog functions',
                },
                {
                    key: Scene.HogFunction,
                    path: urls.hogFunction(id),
                    name: id === 'new' ? 'Create hog function' : 'Edit hog function',
                },
                // {
                //     key: Scene.ErrorTrackingAlert,
                //     name: id === 'new' ? 'Create alert' : 'Edit alert',
                // },
            ],
        ],
    }),
])

export const scene: SceneExport = {
    component: HogFunctionScene,
    logic: hogFunctionSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof hogFunctionSceneLogic)['props'] => ({ id }),
}

export function HogFunctionScene(props: HogFunctionSceneLogicProps): JSX.Element {
    const { currentTab } = useValues(hogFunctionSceneLogic(props))
    const { setCurrentTab } = useActions(hogFunctionSceneLogic(props))
    // Check for hog function and render error if missing
    if (!props) {
        return <div>Error</div>
    }

    const tabs: LemonTab<HogFunctionSceneTab>[] = [
        {
            label: 'Configuration',
            key: 'configuration',
            content: (
                <HogFunctionConfiguration
                    id={props.id}
                    // displayOptions={{ hideTestingConfiguration: false }}
                />
            ),
        },
        {
            label: 'Metrics',
            key: 'metrics',
            content: <HogFunctionMetrics id={props.id} />,
        },
        {
            label: 'Logs',
            key: 'logs',
            content: <HogFunctionLogs hogFunctionId={props.id} />,
        },
        {
            label: 'Testing',
            key: 'testing',
            content: <HogFunctionTesting id={props.id} />,
        },
        {
            label: 'History',
            key: 'history',
            content: <ActivityLog id={props.id} scope={ActivityScope.HOG_FUNCTION} />,
        },
    ]

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} />
}
