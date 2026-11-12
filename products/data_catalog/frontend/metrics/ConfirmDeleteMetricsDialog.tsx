import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

interface ConfirmDeleteMetricsDialogProps {
    open: boolean
    title: string
    description: string
    onClose: () => void
    onConfirm: () => void
    dataAttr: string
}

export function ConfirmDeleteMetricsDialog({
    open,
    title,
    description,
    onClose,
    onConfirm,
    dataAttr,
}: ConfirmDeleteMetricsDialogProps): JSX.Element {
    return (
        <AlertDialog open={open} onOpenChange={(nextOpen: boolean) => !nextOpen && onClose()}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    <AlertDialogDescription>{description}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        onClick={() => {
                            onConfirm()
                            onClose()
                        }}
                        data-attr={dataAttr}
                    >
                        Delete
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
