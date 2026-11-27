import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    FieldError,
} from '@posthog/quill'

import { tagsLogic } from './tagsLogic'

export function DeleteTagModalQuill(): JSX.Element | null {
    const { tagToDelete, mutationLoading, mutationError } = useValues(tagsLogic)
    const { closeModals, submitDelete } = useActions(tagsLogic)
    if (!tagToDelete) {
        return null
    }
    return (
        <AlertDialog
            open
            onOpenChange={(open) => {
                if (!open && !mutationLoading) {
                    closeModals()
                }
            }}
        >
            <AlertDialogContent className="ph-no-capture">
                <AlertDialogHeader>
                    <AlertDialogTitle>{`Delete tag "${tagToDelete.name}"?`}</AlertDialogTitle>
                    <AlertDialogDescription>
                        This tag has no assignments. Deleting it cannot be undone.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                {mutationError && <FieldError>{mutationError}</FieldError>}
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeModals}
                        disabledReason={mutationLoading ? 'Wait for the deletion to finish.' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        loading={mutationLoading}
                        onClick={submitDelete}
                        data-attr="tag-management-delete-confirm"
                    >
                        Delete tag
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
