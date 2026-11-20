import { useId } from 'react'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Badge,
    Button,
    DialogBody,
    Field,
    FieldLabel,
    Input,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { DataWarehouseManagedViewsetSavedQuery } from '~/types'

export interface QuillDataWarehouseManagedViewsetImpactModalProps {
    isOpen: boolean
    onClose: () => void
    title: string
    confirmText: string
    confirmationInput: string
    onConfirmationInputChange: (confirmationInput: string) => void
    views: DataWarehouseManagedViewsetSavedQuery[]
    viewsLoading: boolean
    isDeleting: boolean
    editDisabledReason: string | null
    confirmDisabledReason: string | null
    warningItems: string[]
    infoMessage: string | JSX.Element
    viewsActionText: string
    confirmButtonText: string
    onConfirm: () => Promise<void>
}

export function QuillDataWarehouseManagedViewsetImpactModal({
    isOpen,
    onClose,
    title,
    confirmText,
    confirmationInput,
    onConfirmationInputChange,
    views,
    viewsLoading,
    isDeleting,
    editDisabledReason,
    confirmDisabledReason,
    warningItems,
    infoMessage,
    viewsActionText,
    confirmButtonText,
    onConfirm,
}: QuillDataWarehouseManagedViewsetImpactModalProps): JSX.Element {
    const inputId = useId()

    return (
        <AlertDialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <AlertDialogContent className="sm:max-w-160">
                <AlertDialogHeader>
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                </AlertDialogHeader>

                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Item tone="warning" size="sm">
                            <ItemContent>
                                <ItemTitle>This action will:</ItemTitle>
                                <Text size="xs" render={<ul className="m-0 list-disc list-inside" />}>
                                    {warningItems.map((item, index) => (
                                        <li key={index}>{item}</li>
                                    ))}
                                </Text>
                            </ItemContent>
                        </Item>

                        <Item tone="info" size="sm">
                            <ItemContent>
                                <ItemDescription>{infoMessage}</ItemDescription>
                            </ItemContent>
                        </Item>

                        <div className="flex flex-col gap-2">
                            <Text size="xs" render={<p className="m-0 font-semibold" />}>
                                The following {views.length} view{views.length !== 1 ? 's' : ''} {viewsActionText}:
                            </Text>
                            <div className="flex flex-wrap gap-2">
                                {viewsLoading ? (
                                    <Skeleton className="h-5 w-40" />
                                ) : views.length > 0 ? (
                                    views.map((view) => <Badge key={view.id}>{view.name}</Badge>)
                                ) : (
                                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                        No existing views found.
                                    </Text>
                                )}
                            </div>
                        </div>

                        <Field>
                            <FieldLabel htmlFor={inputId}>
                                <span>
                                    To confirm, type <code>{confirmText}</code> below:
                                </span>
                            </FieldLabel>
                            <Input
                                id={inputId}
                                value={confirmationInput}
                                onChange={(event) => onConfirmationInputChange(event.target.value)}
                                placeholder={`Type "${confirmText}" to confirm`}
                                disabledReason={editDisabledReason}
                                autoFocus
                            />
                        </Field>
                    </div>
                </DialogBody>

                <AlertDialogFooter>
                    <Button variant="outline" onClick={onClose} disabledReason={editDisabledReason}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        loading={isDeleting}
                        disabledReason={confirmDisabledReason}
                        onClick={onConfirm}
                    >
                        {confirmButtonText}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
