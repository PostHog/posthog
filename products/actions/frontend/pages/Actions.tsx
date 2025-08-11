import { SceneExport } from 'scenes/sceneTypes'
import { ActionsTable } from '../components/ActionsTable'
import { actionsLogic } from '../logics/actionsLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { NewActionButton } from '../components/NewActionButton'

export const scene: SceneExport = {
    component: Actions,
    logic: actionsLogic,
}

export function Actions(): JSX.Element {
    return (
        <>
            <PageHeader buttons={<NewActionButton />} />
            <ActionsTable />
        </>
    )
}
