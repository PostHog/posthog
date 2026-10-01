import { useActions, useValues } from 'kea'

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
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'

/** One confirm for the whole selection, shown when any of it is still running. */
export function TodaySessionBulkArchiveDialog(): JSX.Element {
    const { bulkArchiveConfirm, bulkAction } = useValues(todaySessionSelectionLogic)
    const { closeBulkArchiveConfirm, archiveSelected } = useActions(todaySessionSelectionLogic)
    const archiving = bulkAction === 'archive'

    return (
        <AlertDialog
            open={bulkArchiveConfirm.open}
            onOpenChange={(open: boolean) => {
                if (!open && !archiving) {
                    closeBulkArchiveConfirm()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{`Archive ${sessionsLabel(bulkArchiveConfirm.count)}?`}</AlertDialogTitle>
                    <AlertDialogDescription>
                        {bulkArchiveWarning(bulkArchiveConfirm.count, bulkArchiveConfirm.running)}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeBulkArchiveConfirm}
                        disabled={archiving}
                        data-attr="today-session-bulk-archive-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        loading={archiving}
                        onClick={archiveSelected}
                        data-attr="today-session-bulk-archive-confirm"
                    >
                        Archive
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
