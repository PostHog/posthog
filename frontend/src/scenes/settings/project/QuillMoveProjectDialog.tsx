import { useId } from 'react'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Field,
    FieldLabel,
    Input,
} from '@posthog/quill'

export function QuillMoveProjectDialog({
    isOpen,
    onClose,
    onCancel,
    projectName,
    isConfirmed,
    isMoving,
    onConfirmationChange,
    onMove,
}: {
    isOpen: boolean
    /** Undefined while the move is in progress, so the dialog cannot be dismissed. */
    onClose: (() => void) | undefined
    onCancel: () => void
    projectName: string | undefined
    isConfirmed: boolean
    isMoving: boolean
    onConfirmationChange: (value: string) => void
    onMove: (() => void) | undefined
}): JSX.Element {
    const confirmationInputId = useId()

    return (
        <AlertDialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onClose?.()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Move the project to another organization?</AlertDialogTitle>
                    <AlertDialogDescription>
                        Moving a project will mean all original organization members will lose access including via
                        things like API keys unless they also are part of the new organization.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <Field className="px-4">
                    <FieldLabel htmlFor={confirmationInputId}>
                        <span>
                            Please type <strong>{projectName ? projectName : "this project's name"}</strong> to confirm.
                        </span>
                    </FieldLabel>
                    <Input
                        id={confirmationInputId}
                        type="text"
                        onChange={(event) => onConfirmationChange(event.target.value)}
                    />
                </Field>
                <AlertDialogFooter>
                    <Button variant="outline" disabledReason={isMoving ? 'Moving...' : undefined} onClick={onCancel}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        disabledReason={!isConfirmed ? 'Type the project name to confirm' : undefined}
                        loading={isMoving}
                        data-attr="move-project-ok"
                        onClick={onMove}
                    >{`Move ${projectName ? projectName : 'the current project'}`}</Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
