import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

export function QuillDeleteReferencedActionDialog({
    referenceCount,
    onConfirm,
    onCancel,
}: {
    /** How many resources use the action. The dialog is open while this is set. */
    referenceCount: number | null
    onConfirm: () => void
    onCancel: () => void
}): JSX.Element {
    return (
        <AlertDialog
            open={referenceCount !== null}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onCancel()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>This action is used by other resources</AlertDialogTitle>
                    <AlertDialogDescription>
                        This action is referenced by <strong>{referenceCount}</strong> resource
                        {referenceCount === 1 ? '' : 's'}. Deleting it may break them.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={onCancel} data-attr="delete-referenced-action-cancel">
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        onClick={onConfirm}
                        data-attr="delete-referenced-action-confirm"
                    >
                        Delete anyway
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
