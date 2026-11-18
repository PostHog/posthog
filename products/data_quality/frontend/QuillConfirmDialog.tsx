import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

export interface QuillConfirmDialogProps {
    open: boolean
    title: string
    description: string
    confirmLabel: string
    cancelLabel?: string
    onConfirm: () => void
    onCancel: () => void
    dataAttr: string
}

export function QuillConfirmDialog({
    open,
    title,
    description,
    confirmLabel,
    cancelLabel = 'Cancel',
    onConfirm,
    onCancel,
    dataAttr,
}: QuillConfirmDialogProps): JSX.Element {
    return (
        <AlertDialog
            open={open}
            onOpenChange={(nextOpen: boolean) => {
                if (!nextOpen) {
                    onCancel()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    <AlertDialogDescription>{description}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={onCancel} data-attr={`${dataAttr}-cancel`}>
                        {cancelLabel}
                    </Button>
                    <Button variant="destructive-outline" onClick={onConfirm} data-attr={`${dataAttr}-confirm`}>
                        {confirmLabel}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
