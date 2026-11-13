import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { analyticsItemActionsLogic } from './analyticsItemActionsLogic'

/** Confirms deleting the row whose menu asked. */
export function AnalyticsDeleteDialog(): JSX.Element {
    const { deleteTarget, deleting } = useValues(analyticsItemActionsLogic)
    const { closeDeleteConfirm, deleteItem } = useActions(analyticsItemActionsLogic)

    return (
        <AlertDialog
            open={!!deleteTarget}
            // Closing mid-request would let another row's confirmation inherit this one's pending state.
            onOpenChange={(open: boolean) => !open && !deleting && closeDeleteConfirm()}
        >
            <AlertDialogContent data-attr="analytics-delete-dialog">
                <AlertDialogHeader>
                    <AlertDialogTitle>{deleteTarget ? `Delete "${deleteTarget.name}"?` : ''}</AlertDialogTitle>
                    <AlertDialogDescription>
                        It's removed for everyone in the project. You can undo this from the message that follows.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" disabled={deleting} />}>
                        Cancel
                    </AlertDialogClose>
                    <Button
                        variant="destructive-outline"
                        loading={deleting}
                        onClick={() => deleteItem()}
                        data-attr="analytics-delete-confirm"
                    >
                        Delete
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
