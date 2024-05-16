import { SceneExport } from 'scenes/sceneTypes'

import { CliLoginSceneLogic } from './CliLoginSceneLogic'

interface CliLoginSceneProps {
    code?: string
}

export const scene: SceneExport = {
    component: CliLoginScene,
    logic: CliLoginSceneLogic,
    paramsToProps: ({ params: { code } }: { params: CliLoginSceneProps }): CliLoginSceneProps => ({
        code: code || 'missing',
    }),
}

export function CliLoginScene(): JSX.Element {
    return <div />
}
