import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@posthog/quill'

import { WaysToUseSurface } from './waysToUse'
import { waysToUseLogic } from './waysToUseLogic'
import { WaysToUseSurfaces } from './WaysToUseSurfaces'

export function TodayWaysToUseDialog(): JSX.Element {
    const { isOpen } = useValues(waysToUseLogic)
    const { closeWaysToUse } = useActions(waysToUseLogic)

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && closeWaysToUse('dismiss')}>
            <DialogContent size="wide" className="lg:max-w-4xl" data-attr="today-ways-to-use-dialog">
                <DialogHeader className="items-center text-center">
                    <DialogTitle>Use PostHog where you work</DialogTitle>
                    <DialogDescription>
                        Use the web app, ask in Slack, or connect your AI agents and terminal. They all use the same
                        project data.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <WaysToUseSurfaces
                        onSurfaceLinkClick={(surface: WaysToUseSurface) => closeWaysToUse('surface_link', surface)}
                    />
                </DialogBody>
                <DialogFooter className="sm:justify-center">
                    <Button
                        variant="primary"
                        onClick={() => closeWaysToUse('get_started')}
                        data-attr="today-ways-to-use-get-started"
                    >
                        Get started
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
