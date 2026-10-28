import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { DataWarehouseSavedQuery } from '~/types'

import { NodeDetailQueryEditorSync } from './NodeDetailQueryEditorSync'
import { nodeDetailQueryEditorTabId } from './nodeDetailSceneLogic'

export function NodeDetailQueryEditor({
    id,
    savedQuery,
}: {
    id: string
    savedQuery: DataWarehouseSavedQuery
}): JSX.Element {
    const tabId = nodeDetailQueryEditorTabId(savedQuery.id)
    const editorLogic = sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded })
    const { queryInput } = useValues(editorLogic)
    const { editView } = useActions(editorLogic)

    // The logic outlives a tab switch, so only a fresh one is seeded. Opening the view as the editor's
    // tab gives the update the saved query as its baseline, for the conflict check and history head.
    useOnMountEffect(() => {
        if (queryInput === null) {
            editView(savedQuery.query?.query ?? '', savedQuery)
        }
    })

    return (
        // The editor fills its parent, so the parent needs a height.
        <div className="h-[70vh] min-h-96 overflow-hidden rounded border" data-attr="node-detail-query-editor">
            <SQLEditor
                tabId={tabId}
                mode={SQLEditorMode.Embedded}
                showDatabaseTree={false}
                singleStatement
                hideVariables
                hideFilters
                hideAgentHints
                hideAiTools
                showOpenInSqlEditor
                autoFocusQueryPane={false}
                hostSync={<NodeDetailQueryEditorSync id={id} />}
            />
        </div>
    )
}
