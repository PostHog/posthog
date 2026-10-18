import { useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { accessControlLogic } from '../accessControlLogic'

interface QuillRemoveAccessButtonProps {
    onConfirm: () => void
    subject: 'member' | 'role'
}

export function QuillRemoveAccessButton({ onConfirm, subject }: QuillRemoveAccessButtonProps): JSX.Element {
    const { canEditAccessControls } = useValues(accessControlLogic)
    const [confirmOpen, setConfirmOpen] = useState(false)

    return (
        <>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon"
                            aria-label="Remove access"
                            disabled={!canEditAccessControls}
                            onClick={() => setConfirmOpen(true)}
                            data-attr={`access-control-remove-${subject}`}
                        />
                    }
                >
                    <IconTrash />
                </TooltipTrigger>
                <TooltipContent>{canEditAccessControls ? 'Remove access' : 'You cannot edit this'}</TooltipContent>
            </Tooltip>
            <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Remove access</AlertDialogTitle>
                        <AlertDialogDescription>
                            Are you sure you want to remove this {subject}'s explicit access?
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <Button variant="outline" onClick={() => setConfirmOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            variant="destructive-outline"
                            onClick={() => {
                                setConfirmOpen(false)
                                onConfirm()
                            }}
                        >
                            Remove
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    )
}
