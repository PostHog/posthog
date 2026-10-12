import './EditorScene.scss'

import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { AccessDenied } from 'lib/components/AccessDenied'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { editorSceneLogic } from './editorSceneLogic'
import { SQLEditor } from './SQLEditor'
import { SQLEditorMode } from './sqlEditorModes'

export const scene: SceneExport = {
    logic: editorSceneLogic,
    paramsToProps: ({ params }) => ({ tabId: params.tabId ?? 'default' }),
    component: EditorScene,
}

export function EditorScene({ tabId }: { tabId?: string }): JSX.Element {
    const resolvedTabId = tabId ?? 'default'
    const { shareTab } = useActions(editorSceneLogic({ tabId: resolvedTabId }))
    const { isCreateViewFlow } = useValues(editorSceneLogic({ tabId: resolvedTabId }))
    const { setLayoutNavCollapsedOverride } = useActions(panelLayoutLogic)

    // The override follows this component, so the nav returns to the saved choice when the scene leaves the screen.
    useEffect(() => {
        if (!isCreateViewFlow) {
            return
        }
        setLayoutNavCollapsedOverride(true)
        return () => setLayoutNavCollapsedOverride(null)
    }, [isCreateViewFlow, setLayoutNavCollapsedOverride])

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so the SQL editor isn't available." />
        )
    }

    return (
        <SQLEditor tabId={resolvedTabId} mode={SQLEditorMode.FullScene} showDatabaseTree={true} onShareTab={shareTab} />
    )
}
