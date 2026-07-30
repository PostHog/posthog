import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { sqlEditorLogic } from '../sqlEditorLogic'
import { QueryDiffViewer } from './QueryDiffViewer'

export function UpdateViewModal(): JSX.Element | null {
    const { isUpdateViewModalOpen, pendingViewUpdate, editingView, queryInput } = useValues(sqlEditorLogic)
    const { updateView, closeUpdateViewModal } = useActions(sqlEditorLogic)

    if (!editingView) {
        return null
    }

    const isMaterialized = editingView.is_materialized === true
    const confirmLabel = isMaterialized ? 'Update and re-materialize view' : 'Update view'

    return (
        <LemonModal
            title="Review changes"
            description="Compare the saved query with your edits before updating this view."
            isOpen={isUpdateViewModalOpen}
            onClose={closeUpdateViewModal}
            width={800}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeUpdateViewModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            if (pendingViewUpdate) {
                                updateView(pendingViewUpdate.view, pendingViewUpdate.draftId)
                            }
                            closeUpdateViewModal()
                        }}
                    >
                        {confirmLabel}
                    </LemonButton>
                </>
            }
        >
            <QueryDiffViewer original={editingView.query?.query ?? ''} modified={queryInput ?? ''} />
        </LemonModal>
    )
}
