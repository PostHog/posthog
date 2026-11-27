import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { tagsLogic } from './tagsLogic'

export function DeleteTagModal(): JSX.Element | null {
    const { tagToDelete, mutationLoading, mutationError } = useValues(tagsLogic)
    const { closeModals, submitDelete } = useActions(tagsLogic)
    if (!tagToDelete) {
        return null
    }
    return (
        <LemonModal
            title={`Delete tag "${tagToDelete.name}"?`}
            isOpen
            className="ph-no-capture"
            onClose={closeModals}
            closable={!mutationLoading}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModals}
                        disabledReason={mutationLoading ? 'Wait for the deletion to finish.' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        loading={mutationLoading}
                        onClick={submitDelete}
                        data-attr="tag-management-delete-confirm"
                    >
                        Delete tag
                    </LemonButton>
                </>
            }
        >
            <p>This tag has no assignments. Deleting it cannot be undone.</p>
            {mutationError && <LemonBanner type="error">{mutationError}</LemonBanner>}
        </LemonModal>
    )
}
