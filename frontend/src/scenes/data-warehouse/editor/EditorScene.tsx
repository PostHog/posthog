import './EditorScene.scss'

import { useActions } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { editorSceneLogic, SQL_EDITOR_SCENE_TAB_ID } from './editorSceneLogic'
import { SQLEditor } from './SQLEditor'
import { SQLEditorMode } from './sqlEditorModes'

export const scene: SceneExport = {
    logic: editorSceneLogic,
    component: EditorScene,
}

export function EditorScene(): JSX.Element {
    const { shareTab } = useActions(editorSceneLogic)

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so the SQL editor isn't available." />
        )
    }

    return (
        <SQLEditor
            tabId={SQL_EDITOR_SCENE_TAB_ID}
            mode={SQLEditorMode.FullScene}
            showDatabaseTree={true}
            onShareTab={shareTab}
        />
    )
}
