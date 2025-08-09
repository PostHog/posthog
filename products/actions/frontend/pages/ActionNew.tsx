import { SceneItemNew, SceneMainTitle } from '~/layout/scenes/SceneContent'
import { SceneExport } from '~/scenes/sceneTypes'
import { actionEditLogic } from '../logics/actionEditLogic'
import { ActionEdit } from './ActionEdit'

export const scene: SceneExport = {
    component: ActionNew,
    logic: actionEditLogic,
    paramsToProps: (): (typeof actionEditLogic)['props'] => ({ id: undefined }),
}

export function ActionNew(): JSX.Element {
    return (
        <SceneItemNew>
            <SceneMainTitle title="New action" description="Create a new action" />
            <ActionEdit id={undefined} />
        </SceneItemNew>
    )
}
