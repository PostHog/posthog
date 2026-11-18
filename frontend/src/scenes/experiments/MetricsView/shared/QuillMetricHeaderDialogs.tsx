import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillConfirmDialog } from 'products/experiments/frontend/components/QuillConfirmDialog'

import { DUPLICATE_SHARED_METRIC_TITLE, DuplicateSharedMetricCopy, deleteMetricCopy } from './metricHeaderActions'

export function QuillMetricHeaderDialogs({
    dialog,
    onClose,
    isSharedMetric,
    duplicateAsSharedUrl,
    onDuplicateAsSingleUse,
    onDelete,
}: {
    dialog: 'duplicate' | 'delete' | null
    onClose: () => void
    isSharedMetric: boolean
    duplicateAsSharedUrl: string | null
    onDuplicateAsSingleUse: () => void
    onDelete: () => void
}): JSX.Element {
    const deleteCopy = deleteMetricCopy(isSharedMetric)

    return (
        <>
            <Dialog open={dialog === 'duplicate'} onOpenChange={(open: boolean) => !open && onClose()}>
                <DialogContent size="wide" className="max-w-xl" data-attr="experiment-duplicate-shared-metric-modal">
                    <DialogHeader>
                        <DialogTitle>{DUPLICATE_SHARED_METRIC_TITLE}</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <Text size="xs" render={<div className="flex flex-col gap-2" />}>
                            <DuplicateSharedMetricCopy />
                        </Text>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={onClose}>
                            Cancel
                        </Button>
                        {duplicateAsSharedUrl && (
                            <Button
                                variant="outline"
                                nativeButton={false}
                                render={<LinkPrimitive to={duplicateAsSharedUrl} />}
                                onClick={onClose}
                            >
                                Duplicate as shared metric
                            </Button>
                        )}
                        <Button
                            variant="primary"
                            onClick={() => {
                                onDuplicateAsSingleUse()
                                onClose()
                            }}
                        >
                            Duplicate as single-use metric
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
            <QuillConfirmDialog
                open={dialog === 'delete'}
                onOpenChange={(open) => !open && onClose()}
                title={deleteCopy.title}
                description={deleteCopy.description}
                confirmLabel={deleteCopy.label}
                destructive
                onConfirm={onDelete}
                dataAttr="experiment-delete-metric-confirm"
            />
        </>
    )
}
