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

import { canvasHistoryLogic } from './canvasHistoryLogic'

/** Confirms a revert or a draft publish, since either changes what everyone with access sees. */
export function CanvasHistoryConfirmDialog(): JSX.Element {
    const { confirmation, confirming, versionLabels } = useValues(canvasHistoryLogic)
    const { confirm, cancelConfirmation } = useActions(canvasHistoryLogic)
    const revert = confirmation?.kind === 'revert'
    const label = confirmation ? versionLabels[confirmation.versionId] : null

    return (
        <AlertDialog
            open={!!confirmation}
            onOpenChange={(open: boolean) => {
                if (!open && !confirming) {
                    cancelConfirmation()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>
                        {revert ? `Revert to ${label ?? 'this version'}?` : 'Publish this draft?'}
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                        {revert
                            ? 'The canvas goes back to this version and rebuilds. Everyone with access sees it once the build is ready. Newer versions stay in the timeline.'
                            : 'The draft becomes the live canvas. Everyone with access sees it once its build is ready.'}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button variant="outline" disabled={confirming} onClick={() => cancelConfirmation()}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={confirming}
                        onClick={() => confirm()}
                        data-attr={revert ? 'canvas-revert-confirm' : 'canvas-promote-confirm'}
                    >
                        {revert ? 'Revert' : 'Publish'}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
