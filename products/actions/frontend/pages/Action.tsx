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
    // Use the scene-bound logic (BindLogic in App.tsx supplies the key props), so we don't need
    // to duplicate them here.
    const { action, actionLoading } = useValues(actionLogic)

    return (
        <ActionEdit
            id={id}
            action={action}
            actionLoading={actionLoading}
            // Attach actionEditLogic to the scene-kept actionLogic so the form state survives
            // React remounts: useAttachedLogic keeps actionEditLogic alive for as long as
            // actionLogic is mounted.
            attachTo={actionLogic({ id })}
        />
    )
}
