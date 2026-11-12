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

export interface RunActionConfirmation {
    title: string
    description: string
    confirmLabel: string
    destructive: boolean
    onConfirm: () => void
}

export function QuillRunActionConfirmDialog({
    confirmation,
    open,
    onClose,
    onClosed,
}: {
    confirmation: RunActionConfirmation | null
    open: boolean
    onClose: () => void
    onClosed: () => void
}): JSX.Element {
    return (
        <AlertDialog
            open={open}
            onOpenChange={(nextOpen: boolean) => {
                if (!nextOpen) {
                    onClose()
                }
            }}
            onOpenChangeComplete={(nextOpen: boolean) => {
                if (!nextOpen) {
                    onClosed()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{confirmation?.title}</AlertDialogTitle>
                    <AlertDialogDescription>{confirmation?.description}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <Button
                        variant={confirmation?.destructive ? 'destructive-outline' : 'primary'}
                        onClick={() => {
                            confirmation?.onConfirm()
                            onClose()
                        }}
                    >
                        {confirmation?.confirmLabel}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
