import './EditorScene.scss'

import { AccessDenied } from 'lib/components/AccessDenied'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SQLEditor } from './SQLEditor'
import { sqlEditorLogic } from './sqlEditorLogic'
import { SQLEditorMode } from './sqlEditorModes'

export const scene: SceneExport = {
    logic: sqlEditorLogic,
    component: EditorScene,
}

export function EditorScene({ tabId }: { tabId?: string }): JSX.Element {
    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so the SQL editor isn't available." />
        )
    }
    return <SQLEditor tabId={tabId} mode={SQLEditorMode.FullScene} showDatabaseTree={true} />
}
