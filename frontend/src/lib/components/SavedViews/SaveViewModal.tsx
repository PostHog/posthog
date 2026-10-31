import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'

import { GetSavedViewFiltersSummaryLines, SavedViewFiltersSummary } from './SavedViewFiltersSummary'
import { SavedViewPayload, SavedViewsLogicProps, savedViewsLogic } from './savedViewsLogic'

interface SaveViewModalProps {
    logicProps: SavedViewsLogicProps
    savePayload: SavedViewPayload
    getFiltersSummaryLines: GetSavedViewFiltersSummaryLines
}

export function SaveViewModal({
    logicProps,
    savePayload,
    getFiltersSummaryLines,
}: SaveViewModalProps): JSX.Element | null {
    const { isSaveModalOpen, viewName } = useValues(savedViewsLogic(logicProps))
    const { closeSaveModal, setViewName, saveView } = useActions(savedViewsLogic(logicProps))
    const shouldRender = useKeepMountedWhileOpen(isSaveModalOpen)

    if (!shouldRender) {
        return null
    }

    return (
        <LemonModal
            isOpen={isSaveModalOpen}
            onClose={closeSaveModal}
            title="Save current view"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSaveModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => saveView(savePayload)}
                        disabledReason={!viewName.trim() ? 'Enter a name' : undefined}
                    >
                        Save view
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <LemonInput
                    placeholder="View name"
                    value={viewName}
                    onChange={setViewName}
                    autoFocus
                    onPressEnter={() => saveView(savePayload)}
                />
                <SavedViewFiltersSummary
                    filters={(savePayload.filters as Record<string, any> | undefined) ?? {}}
                    getFiltersSummaryLines={getFiltersSummaryLines}
                />
            </div>
        </LemonModal>
    )
}
