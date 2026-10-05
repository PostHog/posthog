import { useActions } from 'kea'

import 'scenes/data-warehouse/editor/EditorScene.scss'
import { AccessDenied } from 'lib/components/AccessDenied'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { editorSceneLogic } from 'scenes/data-warehouse/editor/editorSceneLogic'
import { OutputPane } from 'scenes/data-warehouse/editor/OutputPane'
import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { SceneExport } from 'scenes/sceneTypes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { BIEditor } from './BIEditor'

export const scene: SceneExport = {
    component: BusinessIntelligenceScene,
    logic: editorSceneLogic,
    paramsToProps: ({ params }) => ({
        tabId: `bi-${params.tabId ?? 'default'}`,
        mode: SQLEditorMode.BusinessIntelligence,
    }),
}

export function BusinessIntelligenceScene({ tabId = 'bi-default' }: { tabId?: string }): JSX.Element {
    const { shareTab } = useActions(editorSceneLogic({ tabId, mode: SQLEditorMode.BusinessIntelligence }))

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so Business intelligence isn't available." />
        )
    }

    return (
        <SQLEditor
            tabId={tabId}
            mode={SQLEditorMode.BusinessIntelligence}
            showDatabaseTree={false}
            onShareTab={shareTab}
        >
            <BIEditor tabId={tabId}>
                <OutputPane tabId={tabId} biMode onShareTab={shareTab} />
            </BIEditor>
        </SQLEditor>
    )
}
