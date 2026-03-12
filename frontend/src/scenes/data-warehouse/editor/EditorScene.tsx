import './EditorScene.scss'

import { SceneExport } from 'scenes/sceneTypes'

import { SQLEditor } from './SQLEditor'
import { sqlEditorLogic } from './sqlEditorLogic'
import { SQLEditorMode } from './sqlEditorModes'

export const scene: SceneExport = {
    logic: sqlEditorLogic,
    component: EditorScene,
}

export function EditorScene({ tabId }: { tabId?: string }): JSX.Element {
    return <SQLEditor tabId={tabId} mode={SQLEditorMode.FullScene} showDatabaseTree={true} />
}
