import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { actionLogic, ActionLogicProps } from 'products/actions/frontend/logics/actionLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { ActionType } from '~/types'

import { ActionEdit } from './ActionEdit'

export const scene: SceneExport = {
    logic: actionLogic,
    component: ActionEditPage,
    paramsToProps: ({ params: { id } }): ActionLogicProps => ({ id: id ? parseInt(id) : undefined }),
}

export function ActionEditPage({ id }: { id?: ActionType['id'] } = {}): JSX.Element {
    const { action, actionLoading } = useValues(actionLogic)

    if (actionLoading) {
        return (
            <div className="flex items-center justify-center h-32">
                <Spinner />
            </div>
        )
    }

    if (id && !action) {
        return <NotFound object="action" />
    }

    return <ActionEdit id={id} action={action} />
}
