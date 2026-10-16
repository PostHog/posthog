import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@posthog/quill'

import { analyticsSpacesLogic } from './analyticsSpacesLogic'

/** Confirms deleting a space. Its contents are not deleted, they go back to unfiled. */
export function DeleteSpaceDialog(): JSX.Element {
    const { deletingSpace, deleteInProgress } = useValues(analyticsSpacesLogic)
    const { closeDeleteSpace, deleteSpace } = useActions(analyticsSpacesLogic)

    return (
        <Dialog open={!!deletingSpace} onOpenChange={(open: boolean) => !open && closeDeleteSpace()}>
            <DialogContent data-attr="analytics-delete-space-dialog">
                <DialogHeader>
                    <DialogTitle>{deletingSpace ? `Delete "${deletingSpace.name}"` : 'Delete collection'}</DialogTitle>
                    <DialogDescription>
                        Nothing inside gets deleted. Its dashboards, insights, notebooks and canvases go back to
                        unfiled, outside every collection. Folders in this collection are removed.
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" data-attr="analytics-delete-space-cancel" />}>
                        Cancel
                    </DialogClose>
                    <Button
                        variant="destructive"
                        loading={deleteInProgress}
                        onClick={() => deleteSpace()}
                        data-attr="analytics-delete-space-confirm"
                    >
                        Delete collection
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
