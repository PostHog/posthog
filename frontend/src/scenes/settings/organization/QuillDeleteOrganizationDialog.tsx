import { useId } from 'react'

import {
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
    Text,
} from '@posthog/quill'

import type { OrganizationBasicType } from '~/types'

export function QuillDeleteOrganizationDialog({
    isOpen,
    organization,
    isDeletionConfirmed,
    isDeletionInProgress,
    onClose,
    onConfirmationChange,
    onDelete,
}: {
    isOpen: boolean
    organization: OrganizationBasicType | null
    isDeletionConfirmed: boolean
    isDeletionInProgress: boolean
    onClose: () => void
    onConfirmationChange: (value: string) => void
    onDelete: (() => void) | undefined
}): JSX.Element {
    const inputId = useId()

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open && !isDeletionInProgress) {
                    onClose()
                }
            }}
        >
            <DialogContent showCloseButton={!isDeletionInProgress}>
                <DialogHeader>
                    <DialogTitle>Delete the entire organization?</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-2">
                        <Text size="xs" render={<p className="m-0" />}>
                            Organization deletion <b>cannot be undone</b>. You will lose all data,{' '}
                            <b>including all events</b>, related to all projects within this organization.
                        </Text>
                        <Field>
                            <FieldLabel htmlFor={inputId}>
                                <span>
                                    Please type{' '}
                                    <strong>{organization ? organization.name : "this organization's name"}</strong> to
                                    confirm.
                                </span>
                            </FieldLabel>
                            <Input
                                id={inputId}
                                type="text"
                                onChange={(event) => onConfirmationChange(event.target.value)}
                                data-attr="delete-organization-confirmation-input"
                            />
                        </Field>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" disabled={isDeletionInProgress} onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        disabledReason={!isDeletionConfirmed ? 'Type the organization name to confirm' : undefined}
                        loading={isDeletionInProgress}
                        data-attr="delete-organization-ok"
                        onClick={onDelete}
                    >
                        {`Delete ${organization ? organization.name : 'the current organization'}`}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
