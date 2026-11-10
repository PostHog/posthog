import { useActions, useValues } from 'kea'

import { IconChevronRight, IconRocket } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { TodayGetStarted } from './TodayGetStarted'
import { todayGetStartedLogic } from './todayGetStartedLogic'

const STEP_NAMES = { install: 'Install PostHog', github: 'Connect GitHub', invite: 'Invite your team' }

export function TodaySetupRow(): JSX.Element {
    const { steps, doneCount, guideOpen } = useValues(todayGetStartedLogic)
    const { openGuide, closeGuide, hideGuide } = useActions(todayGetStartedLogic)
    const next = steps.find((step) => !step.done)

    return (
        <>
            <ol className="TodayRows">
                <li className="TodayRow TodaySetupRow" data-interactive>
                    <IconStack className="TodayRow__icons">
                        <IconStackItem color="var(--color-product-product-analytics-light)">
                            <IconRocket />
                        </IconStackItem>
                    </IconStack>
                    <div className="min-w-0">
                        <button
                            type="button"
                            className="TodayRow__title TodayRow__link TodaySetupRow__open"
                            onClick={openGuide}
                            data-attr="today-get-started-open"
                        >
                            Finish setting up PostHog
                        </button>
                        <p className="TodayRow__meta">
                            <span translate="no">{`${doneCount} of ${steps.length} done`}</span>
                            {next ? <span>{` · Next: ${STEP_NAMES[next.key]}`}</span> : null}
                        </p>
                    </div>
                    <div className="TodayRow__end">
                        <IconChevronRight className="TodayRow__arrow" aria-hidden />
                    </div>
                </li>
            </ol>
            <Dialog open={guideOpen} onOpenChange={(open: boolean) => (open ? openGuide() : closeGuide())}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Set up PostHog</DialogTitle>
                        <DialogDescription>
                            <span translate="no">{`${doneCount} of ${steps.length} done. `}</span>
                            <span>Install PostHog, connect your code and bring in your team.</span>
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <TodayGetStarted />
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={hideGuide} data-attr="today-get-started-hide">
                            Hide this guide
                        </Button>
                        <Button variant="primary" onClick={closeGuide} data-attr="today-get-started-close">
                            Done
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}
