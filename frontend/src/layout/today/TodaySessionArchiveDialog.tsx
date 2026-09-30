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

import { todaySessionMenuLogic } from './todaySessionMenuLogic'

interface TodaySessionArchiveDialogProps {
    sessionId: string
    title: string
    runId: string
}

export function TodaySessionArchiveDialog({ sessionId, title, runId }: TodaySessionArchiveDialogProps): JSX.Element {
    const { pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { closeArchiveConfirm, confirmArchive } = useActions(todaySessionMenuLogic)
    const pending = pendingSessionIds.includes(sessionId)

    return (
        <AlertDialog
            open
            onOpenChange={(open: boolean) => {
                if (!open && !pending) {
                    closeArchiveConfirm()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Archive running session?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {`${title ? `“${title}”` : 'This session'} is still running. Archiving it will stop its cloud run and shut down the sandbox. You can unarchive it later.`}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeArchiveConfirm}
                        disabled={pending}
                        data-attr="today-session-archive-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        loading={pending}
                        onClick={() => confirmArchive(sessionId, runId)}
                        data-attr="today-session-archive-confirm"
                    >
                        Archive
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
