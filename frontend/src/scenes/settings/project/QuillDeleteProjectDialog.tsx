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
    Item,
    ItemContent,
    ItemDescription,
    Text,
} from '@posthog/quill'

export function QuillDeleteProjectDialog({
    isOpen,
    onClose,
    onCancel,
    projectName,
    environmentNames,
    isDeletionConfirmed,
    isDeletionInProgress,
    onConfirmationChange,
    onDelete,
}: {
    isOpen: boolean
    /** Undefined while the deletion is in progress, so the dialog cannot be dismissed. */
    onClose: (() => void) | undefined
    onCancel: () => void
    projectName: string | undefined
    environmentNames: { id: number; name: string }[]
    isDeletionConfirmed: boolean
    isDeletionInProgress: boolean
    onConfirmationChange: (value: string) => void
    onDelete: (() => void) | undefined
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
                    <AlertDialogTitle>Delete the project and its data?</AlertDialogTitle>
                    <AlertDialogDescription>
                        Project deletion <b>cannot be undone</b>. You will lose all environments and their data (
                        <b>including events</b>):
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="flex flex-col gap-3 px-4">
                    <ul className="list-disc list-inside m-0 ps-2">
                        {environmentNames.map((environment) => (
                            <Text key={environment.id} size="xs" render={<li />}>
                                {environment.name}
                            </Text>
                        ))}
                    </ul>
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                <strong>Note:</strong> For projects with lots of data, cleanup may take several hours.
                                We'll send you an email when the process is complete.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                    <Field>
                        <FieldLabel htmlFor={confirmationInputId}>
                            <span>
                                Please type <strong>{projectName ? projectName : "this project's name"}</strong> to
                                confirm.
                            </span>
                        </FieldLabel>
                        <Input
                            id={confirmationInputId}
                            type="text"
                            onChange={(event) => onConfirmationChange(event.target.value)}
                        />
                    </Field>
                </div>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        disabledReason={isDeletionInProgress ? 'Deleting...' : undefined}
                        onClick={onCancel}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        disabledReason={!isDeletionConfirmed ? 'Type the project name to confirm' : undefined}
                        loading={isDeletionInProgress}
                        data-attr="delete-project-ok"
                        onClick={onDelete}
                    >{`Delete ${projectName ? projectName : 'the current project'}`}</Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
