import { useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { sqlEditorLogic } from './sqlEditorLogic'
import { updateViewLabel } from './updateViewLabel'
import { useUpdateEditingView } from './useUpdateEditingView'

/**
 * Saving an edited view otherwise means leaving the editor for the button in the scene header, so
 * this repeats it over the pane the edit happened in. It shares `useUpdateEditingView` with that
 * button, so both stay disabled for the same reasons, including until the edited query has run.
 * The pane already diffs the edit, so this saves directly instead of opening the review again.
 */
export function QueryPaneSaveBar(): JSX.Element | null {
    const { editingView, changesToSave } = useValues(sqlEditorLogic)
    const { disabledReason, loading, isMaterializedView, commit } = useUpdateEditingView()

    if (!editingView || !changesToSave) {
        return null
    }

    return (
        <div
            // The 2rem keeps a gutter on both sides of a centred, absolutely positioned bar, so a
            // narrow pane wraps the button under the label instead of running it past the edge.
            className="absolute bottom-4 left-1/2 z-10 flex max-w-[calc(100%-2rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-2 rounded border bg-bg-light px-2 py-1 shadow-md"
            data-attr="query-pane-save-bar"
        >
            <span className="truncate text-muted">Unsaved changes</span>
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
    )
}
