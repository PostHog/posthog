import { LemonButton, LemonModal } from '@posthog/lemon-ui'

interface SavedViewDeleteModalProps {
    isOpen: boolean
    name: string | null | undefined
    isDeleting: boolean
    onClose: () => void
    onDelete: () => void
}

export function SavedViewDeleteModal({
    isOpen,
    name,
    isDeleting,
    onClose,
    onDelete,
}: SavedViewDeleteModalProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Delete view"
            description={`Are you sure you want to delete the view "${name ?? ''}"?`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={onDelete}
                        loading={isDeleting}
                        disabledReason={isDeleting ? 'Deleting...' : undefined}
                    >
                        Delete
                    </LemonButton>
                </>
            }
        />
    )
}
