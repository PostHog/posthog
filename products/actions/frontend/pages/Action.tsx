import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { ActionLogicProps, actionLogic } from 'products/actions/frontend/logics/actionLogic'

import { ActionEdit } from './ActionEdit'

export const scene: SceneExport<ActionLogicProps> = {
    logic: actionLogic,
    component: Action,
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) }),
}

export function Action({ id }: ActionLogicProps): JSX.Element {
    const { action, actionLoading } = useValues(actionLogic({ id }))

    return <ActionEdit id={id} action={action} actionLoading={actionLoading} />
}
