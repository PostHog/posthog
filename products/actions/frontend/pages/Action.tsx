import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { ActionLogicProps, actionLogic } from 'products/actions/frontend/logics/actionLogic'

import { ActionEdit } from './ActionEdit'

export const scene: SceneExport<ActionLogicProps> = {
    logic: actionLogic,
    component: Action,
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) }),
}

export function Action({ id, tabId }: ActionLogicProps): JSX.Element {
    // Use the scene-bound logic (BindLogic in App.tsx supplies tabId), so we don't need to
    // duplicate the key props here.
    const { action, actionLoading } = useValues(actionLogic)

    return (
        <ActionEdit
            id={id}
            tabId={tabId}
            action={action}
            actionLoading={actionLoading}
            // Attach actionEditLogic to the scene-kept actionLogic so the form state survives
            // tab switches: sceneLogic keeps actionLogic mounted per tab, and useAttachedLogic
            // keeps actionEditLogic alive for as long as actionLogic is mounted.
            attachTo={actionLogic({ id, tabId })}
        />
    )
}
