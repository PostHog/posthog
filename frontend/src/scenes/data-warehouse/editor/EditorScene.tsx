import './EditorScene.scss'

import { BindLogic, useActions, useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { editorSceneLogic } from './editorSceneLogic'
import { SQLEditor } from './SQLEditor'
import { SQLEditorMode } from './sqlEditorModes'
import { SqlEditorTabsBar } from './SqlEditorTabsBar'
import { sqlEditorTabsLogic } from './sqlEditorTabsLogic'

export const scene: SceneExport = {
    logic: editorSceneLogic,
    component: EditorScene,
}

export function EditorScene({ tabId }: { tabId?: string }): JSX.Element {
    const { tabs, activeTabId } = useValues(sqlEditorTabsLogic)

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so the SQL editor isn't available." />
        )
    }

    // Always include the scene-provided tabId so it renders even before sceneLogic.tabs
    // bubbles up (first paint after navigation).
    const renderTabs = tabs.length > 0 ? tabs : tabId ? [{ id: tabId, label: 'Query 1' }] : []
    const renderActiveId = activeTabId || tabId || renderTabs[0]?.id || ''

    return (
        <div className="flex h-full min-h-0 flex-col">
            <SqlEditorTabsBar />
            <div className="relative flex min-h-0 flex-1">
                {renderTabs.map((tab) => (
                    <div
                        key={tab.id}
                        className={cn(
                            'absolute inset-0 flex min-h-0 flex-col',
                            tab.id === renderActiveId ? '' : 'pointer-events-none invisible'
                        )}
                        aria-hidden={tab.id !== renderActiveId}
                    >
                        <EditorTabInstance tabId={tab.id} />
                    </div>
                ))}
            </div>
        </div>
    )
}

function EditorTabInstance({ tabId }: { tabId: string }): JSX.Element {
    const { shareTab } = useActions(editorSceneLogic({ tabId }))

    return (
        <BindLogic logic={editorSceneLogic} props={{ tabId }}>
            <SQLEditor tabId={tabId} mode={SQLEditorMode.FullScene} showDatabaseTree onShareTab={shareTab} />
        </BindLogic>
    )
}
