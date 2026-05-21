import './EditorScene.scss'

import { useActions } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { editorSceneLogic } from './editorSceneLogic'
import { SQLEditor } from './SQLEditor'
import { SQLEditorMode } from './sqlEditorModes'

export const scene: SceneExport = {
    logic: editorSceneLogic,
    component: EditorScene,
}

export function EditorScene({ tabId }: { tabId?: string }): JSX.Element {
    const resolvedTabId = tabId ?? 'default'
    const { shareTab } = useActions(editorSceneLogic({ tabId: resolvedTabId }))

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so the SQL editor isn't available." />
        )
    }

    return (
        <SQLEditor tabId={resolvedTabId} mode={SQLEditorMode.FullScene} showDatabaseTree={true} onShareTab={shareTab} />
    )
}
