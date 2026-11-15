import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { bulkArchiveWarning, sessionsLabel } from './todaySessionSelection'
import { TodayBulkArchiveConfirm } from './todaySessionSelectionLogic'

interface TodaySessionBulkArchiveDialogProps {
    confirm: TodayBulkArchiveConfirm
    archiving: boolean
    onCancel: () => void
    onConfirm: () => void
    /** Starts each button's `data-attr`, so every surface counts on its own. */
    dataAttrPrefix: string
}

/** One confirm for the whole selection, shown when any of it is still running. */
export function TodaySessionBulkArchiveDialog({
    confirm,
    archiving,
    onCancel,
    onConfirm,
    dataAttrPrefix,
}: TodaySessionBulkArchiveDialogProps): JSX.Element {
    return (
        <AlertDialog
            open={confirm.open}
            onOpenChange={(open: boolean) => {
                if (!open && !archiving) {
                    onCancel()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{`Archive ${sessionsLabel(confirm.count)}?`}</AlertDialogTitle>
                    <AlertDialogDescription>
                        {bulkArchiveWarning(confirm.count, confirm.running)}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={onCancel}
                        disabled={archiving}
                        data-attr={`${dataAttrPrefix}-archive-cancel`}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        loading={archiving}
                        onClick={onConfirm}
                        data-attr={`${dataAttrPrefix}-archive-confirm`}
                    >
                        Archive
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
