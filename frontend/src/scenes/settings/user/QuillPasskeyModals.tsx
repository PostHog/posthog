import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { passkeySettingsLogic } from './passkeySettingsLogic'

export function QuillPasskeyModals({
    renameLabel,
    onRenameLabelChange,
    onRename,
    onDelete,
}: {
    renameLabel: string
    onRenameLabelChange: (label: string) => void
    onRename: () => void
    onDelete: () => void
}): JSX.Element {
    const { deleteModalId, renameModal } = useValues(passkeySettingsLogic)
    const { closeDeleteModal, closeRenameModal } = useActions(passkeySettingsLogic)
    const renameInputId = useId()

    return (
        <>
            <AlertDialog
                open={deleteModalId !== null}
                onOpenChange={(nextOpen: boolean) => !nextOpen && closeDeleteModal()}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete passkey?</AlertDialogTitle>
                        <AlertDialogDescription>
                            Are you sure you want to delete this passkey? You won't be able to use it to sign in
                            anymore.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                        <Button variant="destructive-outline" onClick={onDelete}>
                            Delete
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>

            <Dialog open={renameModal !== null} onOpenChange={(nextOpen: boolean) => !nextOpen && closeRenameModal()}>
                <DialogContent>
                    <form
                        className="contents"
                        onSubmit={(event) => {
                            event.preventDefault()
                            onRename()
                        }}
                    >
                        <DialogHeader>
                            <DialogTitle>Rename passkey</DialogTitle>
                        </DialogHeader>
                        <DialogBody>
                            <Field>
                                <FieldLabel htmlFor={renameInputId} className="sr-only">
                                    Passkey name
                                </FieldLabel>
                                <Input
                                    id={renameInputId}
                                    value={renameLabel}
                                    onChange={(event) => onRenameLabelChange(event.target.value)}
                                    placeholder="Passkey name"
                                    autoFocus
                                    maxLength={200}
                                />
                            </Field>
                        </DialogBody>
                        <DialogFooter>
                            <Button variant="outline" onClick={closeRenameModal}>
                                Cancel
                            </Button>
                            <Button
                                variant="primary"
                                type="submit"
                                disabledReason={!renameLabel.trim() ? 'Name is required' : undefined}
                            >
                                Save
                            </Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>
        </>
    )
}
