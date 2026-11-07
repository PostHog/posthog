import { useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { QueryPaneFloatingBar } from './QueryPaneFloatingBar'
import { sqlEditorLogic } from './sqlEditorLogic'
import { updateViewLabel } from './updateViewLabel'
import { useDiscardEditingView } from './useDiscardEditingView'
import { useUpdateEditingView } from './useUpdateEditingView'

/**
 * Acting on an edited view otherwise means leaving the editor for the buttons in the scene header,
 * so this repeats them over the pane the edit happened in. It shares their hooks, so the two sets
 * stay disabled for the same reasons, including until the edited query has run. The pane already
 * diffs the edit, so saving here commits instead of opening the review again.
 */
export function QueryPaneSaveBar(): JSX.Element | null {
    const { editingView, changesToSave } = useValues(sqlEditorLogic)
    const { disabledReason, loading, isMaterializedView, commit } = useUpdateEditingView()
    const { disabledReason: discardDisabledReason, discard } = useDiscardEditingView()

    if (!editingView || !changesToSave) {
        return null
    }

    return (
        <QueryPaneFloatingBar>
            <div className="flex flex-col items-center gap-1 px-2 py-1.5" data-attr="query-pane-save-bar">
                <span className="truncate text-xs text-muted">Unsaved changes</span>
                <div className="flex flex-wrap items-center justify-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => discard()}
                        disabledReason={discardDisabledReason}
                        data-attr="query-pane-save-bar-discard"
                    >
                        Discard changes
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => commit()}
                        disabledReason={disabledReason}
                        loading={loading}
                        data-attr="query-pane-save-bar-update"
                    >
                        {updateViewLabel(isMaterializedView)}
                    </LemonButton>
                </div>
            </div>
        </QueryPaneFloatingBar>
    )
}
