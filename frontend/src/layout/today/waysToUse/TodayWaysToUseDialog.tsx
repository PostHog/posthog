import { useActions, useValues } from 'kea'
import { useRef } from 'react'

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

import { waysToUseLogic } from './waysToUseLogic'
import { WaysToUseSurfaces } from './WaysToUseSurfaces'

export function TodayWaysToUseDialog(): JSX.Element {
    const { isOpen } = useValues(waysToUseLogic)
    const { closeWaysToUse } = useActions(waysToUseLogic)
    const popupRef = useRef<HTMLDivElement>(null)

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && closeWaysToUse('dismiss')}>
            <DialogContent
                ref={popupRef}
                size="wide"
                initialFocus={popupRef}
                className="group/popup lg:max-w-4xl"
                data-attr="today-ways-to-use-dialog"
            >
                <DialogHeader className="items-center text-center">
                    <DialogTitle className="text-lg">Use PostHog where you work</DialogTitle>
                    <DialogDescription className="max-w-xl text-balance">
                        Use the web app, ask in Slack, or connect your AI agents. They all use the same project data.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <WaysToUseSurfaces onSurfaceLinkClick={(surface) => closeWaysToUse('surface_link', surface)} />
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
