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

export function QuillDisable2FADialog({
    open,
    onClose,
    onConfirm,
}: {
    open: boolean
    onClose: () => void
    onConfirm: () => void
}): JSX.Element {
    return (
        <AlertDialog open={open} onOpenChange={(nextOpen: boolean) => !nextOpen && onClose()}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Disable authenticator app</AlertDialogTitle>
                    <AlertDialogDescription>
                        Are you sure you want to disable 2FA using an authenticator app? This will make your account
                        less secure.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <Button variant="destructive-outline" onClick={onConfirm}>
                        Disable 2FA
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
