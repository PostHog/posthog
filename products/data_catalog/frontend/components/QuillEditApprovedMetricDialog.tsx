import {
    Button,
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@posthog/quill'

export interface QuillEditApprovedMetricDialogProps {
    open: boolean
    isDrifted: boolean
    onSaveAndApprove: () => void
    onSaveAndReset: () => void
    onCancel: () => void
}

export function QuillEditApprovedMetricDialog({
    open,
    isDrifted,
    onSaveAndApprove,
    onSaveAndReset,
    onCancel,
}: QuillEditApprovedMetricDialogProps): JSX.Element {
    return (
        <Dialog open={open} onOpenChange={(nextOpen: boolean) => !nextOpen && onCancel()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Edit this approved metric?</DialogTitle>
                    <DialogDescription>
                        Saving this change sets the metric back to proposed. Approve it again now, or leave it for a
                        teammate to review.
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter className="flex-wrap">
                    <Button variant="outline" onClick={onSaveAndReset} data-attr="data-catalog-metric-save-and-reset">
                        Save and reset to proposed
                    </Button>
                    <Button
                        variant="primary"
                        onClick={onSaveAndApprove}
                        disabledReason={
                            isDrifted
                                ? 'This metric has drifted from its source insight. Refresh it before approving.'
                                : undefined
                        }
                        data-attr="data-catalog-metric-save-and-approve"
                    >
                        Save and approve
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
