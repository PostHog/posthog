import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { notebookLogic } from './notebookLogic'
import { NotebookPreview } from './NotebookPreview'

export function NotebookStaleConflictModal(): JSX.Element | null {
    const { staleConflict } = useValues(notebookLogic)
    const { dismissStaleConflict, discardLocalChanges, copyUnsavedToNewNotebook } = useActions(notebookLogic)

    if (!staleConflict) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={dismissStaleConflict}
            title="We couldn't sync your changes"
            description="The notebook has changed too much since you started typing. We can't reconcile the changes automatically."
            footer={
                <>
                    <LemonButton type="secondary" onClick={discardLocalChanges}>
                        Discard unsaved changes and reload
                    </LemonButton>
                    <LemonButton type="primary" onClick={copyUnsavedToNewNotebook}>
                        Copy unsaved version to a new notebook
                    </LemonButton>
                </>
            }
            width={1200}
        >
            <div className="grid grid-cols-2 border rounded overflow-hidden">
                <div className="border-r">
                    <div className="p-2 border-b text-xs font-medium text-secondary bg-surface-secondary">
                        Last saved version
                    </div>
                    <div className="p-3 max-h-96 overflow-auto">
                        <NotebookPreview content={staleConflict.serverContent} />
                    </div>
                </div>
                <div>
                    <div className="p-2 border-b text-xs font-medium text-secondary bg-surface-secondary">
                        Your unsaved changes
                    </div>
                    <div className="p-3 max-h-96 overflow-auto">
                        <NotebookPreview content={staleConflict.localContent} />
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
