import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Text,
} from '@posthog/quill'

export function QuillDeleteLastTriggerGroupDialog({
    isOpen,
    onClose,
    onConfirm,
    groupName,
}: {
    isOpen: boolean
    onClose: () => void
    onConfirm: () => void
    groupName: string
}): JSX.Element {
    return (
        <AlertDialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete last trigger group?</AlertDialogTitle>
                    <AlertDialogDescription>
                        "{groupName}" is your only trigger group. Deleting it will replace it with a default group that{' '}
                        <strong>records all sessions</strong>, so your project keeps using trigger groups.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    To record a subset of sessions instead, edit the group's conditions or sample rate rather than
                    deleting it. To stop recording entirely, disable session recording in General settings.
                </Text>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <Button
                        variant="destructive-outline"
                        onClick={onConfirm}
                        data-attr="trigger-group-delete-last-confirm"
                    >
                        Delete and record all sessions
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
