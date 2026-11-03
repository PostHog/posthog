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
    onClose,
}: {
    confirmation: RunActionConfirmation | null
    onClose: () => void
}): JSX.Element {
    return (
        <AlertDialog
            open={!!confirmation}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onClose()
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
