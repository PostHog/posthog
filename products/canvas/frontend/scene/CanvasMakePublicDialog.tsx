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

import { canvasSceneLogic } from './canvasSceneLogic'

export function CanvasMakePublicDialog(): JSX.Element {
    const { canvas, visibilityChanging } = useValues(canvasSceneLogic)
    const { closeMakePublic, setCanvasVisibility } = useActions(canvasSceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const project = currentTeam?.name ? `Everyone in ${currentTeam.name}` : 'Everyone in this project'
    const name = canvas?.name ? `“${canvas.name}”` : 'this canvas'

    return (
        <AlertDialog
            open
            onOpenChange={(open: boolean) => {
                if (!open && !visibilityChanging) {
                    closeMakePublic()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Make this canvas public?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {`${project} will be able to open and edit ${name}. Only you can rename it or make it private again.`}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => closeMakePublic()}
                        disabled={visibilityChanging}
                        data-attr="canvas-make-public-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={visibilityChanging}
                        onClick={() => setCanvasVisibility('public')}
                        data-attr="canvas-make-public-confirm"
                    >
                        <IconGlobe />
                        Make public
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
