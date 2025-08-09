import { SceneExport } from 'scenes/sceneTypes'
import { ActionsTable } from '../components/ActionsTable'
import { actionsLogic } from '../logics/actionsLogic'

export const scene: SceneExport = {
    component: Actions,
    logic: actionsLogic,
}

export function Actions(): JSX.Element {
    return (
        <>
            <ActionsTable />
        </>
    )
}
