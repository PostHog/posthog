import { connect, kea, path, props, selectors } from 'kea'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { hogFunctionConfigurationLogic } from 'scenes/pipeline/hogfunctions/hogFunctionConfigurationLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

export type HogFunctionNewSceneLogicProps = { id: string }

export const hogFunctionNewSceneLogic = kea<hogFunctionNewSceneLogicType>([
    path((key) => ['scenes', 'hog-functions', 'hogFunctionNewSceneLogic', key]),
    props({} as HogFunctionNewSceneLogicProps),
    connect(({ id }: HogFunctionNewSceneLogicProps) => ({
        values: [
            hogFunctionConfigurationLogic({
                templateId: id,
            }),
            ['configuration'],
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
            ],
        ],
    }),
])

export const scene: SceneExport = {
    component: HogFunctionNewScene,
    logic: hogFunctionNewSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof hogFunctionNewSceneLogic)['props'] => ({ id }),
}

export function HogFunctionNewScene(props: HogFunctionNewSceneLogicProps): JSX.Element {
    // Check for hog function and render error if missing
    if (!props) {
        return <div>Error</div>
    }

    console.log('props', props)

    return (
        <>
            <HogFunctionConfiguration
                templateId={props.id}
                // displayOptions={{ hideTestingConfiguration: false }}
            />
        </>
    )
}
