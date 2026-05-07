import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonModal } from '@posthog/lemon-ui'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'

import { notebookLogic } from './notebookLogic'

export function NotebookStaleConflictModal(): JSX.Element | null {
    const { staleConflict } = useValues(notebookLogic)
    const { dismissStaleConflict, discardLocalChanges, forceSaveLocalChanges } = useActions(notebookLogic)

    if (!staleConflict) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={dismissStaleConflict}
            title="We couldn't sync your changes"
            description="The notebook has changed too much since you started typing. We can't merge your changes automatically."
            footer={
                <>
                    <LemonButton type="secondary" onClick={discardLocalChanges}>
                        Discard my changes
                    </LemonButton>
                    <LemonButton type="primary" status="danger" onClick={forceSaveLocalChanges}>
                        Save anyway
                    </LemonButton>
                </>
            }
            width={900}
        >
            <p className="text-secondary">
                Your local edits are preserved here. Choose to discard them, or overwrite the server's version.
            </p>
            <LemonCollapse
                panels={[
                    {
                        key: 'preview',
                        header: 'Preview changes',
                        content: (
                            <MonacoDiffEditor
                                original={staleConflict.serverText}
                                modified={staleConflict.localText}
                                language="markdown"
                                options={{
                                    readOnly: true,
                                    renderSideBySide: true,
                                    minimap: { enabled: false },
                                    scrollBeyondLastLine: false,
                                    hideUnchangedRegions: { enabled: true },
                                }}
                            />
                        ),
                    },
                ]}
            />
        </LemonModal>
    )
}
