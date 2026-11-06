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
    /** Set while another access change is saving, so removals and level changes never overlap. */
    disabledReason?: string
}

export function QuillRemoveAccessButton({
    onConfirm,
    subject,
    disabledReason: reasonFromCaller,
}: QuillRemoveAccessButtonProps): JSX.Element {
    const { canEditAccessControls } = useValues(accessControlLogic)
    const [confirmOpen, setConfirmOpen] = useState(false)
    const disabledReason = canEditAccessControls ? reasonFromCaller : 'You cannot edit this'

    return (
        <>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon"
                            aria-label="Remove access"
                            disabled={!!disabledReason}
                            onClick={() => setConfirmOpen(true)}
                            data-attr={`access-control-remove-${subject}`}
                        />
                    }
                >
                    <IconTrash />
                </TooltipTrigger>
                <TooltipContent>{disabledReason ?? 'Remove access'}</TooltipContent>
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
