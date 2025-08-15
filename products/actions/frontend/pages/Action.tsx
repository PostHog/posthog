import { useValues } from 'kea'
import { actionLogic, ActionLogicProps } from 'products/actions/frontend/logics/actionLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ActionType } from '~/types'
import { ActionEdit } from './ActionEdit'

export const scene: SceneExport = {
    logic: actionLogic,
    component: Action,
    paramsToProps: ({ params: { id } }): ActionLogicProps => ({ id: id ? parseInt(id) : undefined }),
}

export function Action({ id }: { id?: ActionType['id'] } = {}): JSX.Element {
    const { action, actionLoading } = useValues(actionLogic({ id }))

    return <ActionEdit id={id} action={action} actionLoading={actionLoading} />
}
