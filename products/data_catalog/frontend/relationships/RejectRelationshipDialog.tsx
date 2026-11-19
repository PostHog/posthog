import { useActions } from 'kea'
import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Textarea,
} from '@posthog/quill'

import { relationshipsLogic } from '../relationshipsLogic'

interface RejectRelationshipDialogProps {
    proposalId: string
    open: boolean
    onClose: () => void
}

export function RejectRelationshipDialog({ proposalId, open, onClose }: RejectRelationshipDialogProps): JSX.Element {
    const { rejectProposal } = useActions(relationshipsLogic)
    const [rejectionReason, setRejectionReason] = useState('')
    const reasonFieldId = `data-catalog-reject-reason-${proposalId}`

    return (
        <Dialog open={open} onOpenChange={(nextOpen: boolean) => !nextOpen && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Reject this relationship?</DialogTitle>
                    <DialogDescription>
                        Rejecting is permanent: this table pair will not be proposed again.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <Field>
                        <FieldLabel htmlFor={reasonFieldId}>Reason (optional)</FieldLabel>
                        <Textarea
                            id={reasonFieldId}
                            placeholder="Why is this join wrong?"
                            value={rejectionReason}
                            onChange={(event) => setRejectionReason(event.target.value)}
                        />
                    </Field>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        onClick={() => {
                            rejectProposal(proposalId, rejectionReason)
                            onClose()
                        }}
                        data-attr="data-catalog-reject-relationship-confirm"
                    >
                        Reject
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
