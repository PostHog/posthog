import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { TAG_REFERENCE_WARNING, tagsLogic } from './tagsLogic'

export function RenameTagModal(): JSX.Element | null {
    const { tagToRename, renameName, mutationLoading, mutationError } = useValues(tagsLogic)
    const { closeModals, setRenameName, submitRename } = useActions(tagsLogic)
    if (!tagToRename) {
        return null
    }
    return (
        <LemonModal
            title="Rename tag"
            isOpen
            className="ph-no-capture"
            onClose={closeModals}
            closable={!mutationLoading}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModals}
                        disabledReason={mutationLoading ? 'Wait for the rename to finish.' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitRename}
                        loading={mutationLoading}
                        disabledReason={!renameName.trim() ? 'Enter a tag name.' : undefined}
                        data-attr="tag-management-rename-confirm"
                    >
                        Rename tag
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <LemonLabel htmlFor="rename-tag-name">Tag name</LemonLabel>
                <LemonInput
                    id="rename-tag-name"
                    value={renameName}
                    onChange={setRenameName}
                    onPressEnter={submitRename}
                    maxLength={255}
                    disabled={mutationLoading}
                    autoFocus
                    data-attr="tag-management-rename-name"
                />
                <LemonBanner type="warning">{TAG_REFERENCE_WARNING}</LemonBanner>
                {mutationError && <LemonBanner type="error">{mutationError}</LemonBanner>}
            </div>
        </LemonModal>
    )
}
