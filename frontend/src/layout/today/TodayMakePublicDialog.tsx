import { useActions, useValues } from 'kea'

import { IconGlobe } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'

interface TodayMakePublicDialogProps {
    sessionId: string
    title: string
    previousSpaceId: string | null
}

export function TodayMakePublicDialog({ sessionId, title, previousSpaceId }: TodayMakePublicDialogProps): JSX.Element {
    const { pendingSessionIds, makePublicRequest } = useValues(todaySessionMenuLogic)
    const { closeMakePublic, setSessionVisibility } = useActions(todaySessionMenuLogic)
    const { currentTeam } = useValues(teamLogic)
    const pending = pendingSessionIds.includes(sessionId)
    const project = currentTeam?.name ? `everyone in ${currentTeam.name}` : 'everyone in this project'

    return (
        <AlertDialog
            open
            onOpenChange={(open: boolean) => {
                if (!open && !pending) {
                    closeMakePublic()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Make this chat public?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {`After this, ${project} can see ${title ? `“${title}”` : 'this chat'}: its messages, and the files and pull requests it made. You can move it back to personal at any time.`}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeMakePublic}
                        disabled={pending}
                        data-attr="today-chat-make-public-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={pending}
                        onClick={() =>
                            setSessionVisibility(
                                sessionId,
                                'public',
                                previousSpaceId,
                                makePublicRequest?.source ?? 'menu'
                            )
                        }
                        data-attr="today-chat-make-public-confirm"
                    >
                        <IconGlobe />
                        Make public
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
