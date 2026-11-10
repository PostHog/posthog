import { useActions, useValues } from 'kea'

import {
    IconCheckCircle,
    IconChevronRight,
    IconCircleDashed,
    IconHide,
    IconMinusSquare,
    IconRocket,
} from '@posthog/icons'
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
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TodayGetStarted } from './TodayGetStarted'
import { todayGetStartedLogic } from './todayGetStartedLogic'

const STEP_NAMES = { install: 'Install PostHog', github: 'Connect GitHub', invite: 'Invite your team' }

export function TodaySetupRow(): JSX.Element {
    const { steps, doneCount, guideOpen } = useValues(todayGetStartedLogic)
    const { openGuide, closeGuide, hideGuide } = useActions(todayGetStartedLogic)
    const next = steps.find((step) => !step.done && !step.skipped)

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
                        <ul className="TodaySetupRow__steps" aria-label={`${doneCount} of ${steps.length} steps done`}>
                            {steps.map((step) => (
                                <li
                                    key={step.key}
                                    className="TodaySetupRow__step"
                                    data-state={
                                        step.done
                                            ? 'done'
                                            : step.skipped
                                              ? 'skipped'
                                              : step.key === next?.key
                                                ? 'next'
                                                : 'todo'
                                    }
                                >
                                    {step.done ? (
                                        <IconCheckCircle className="TodaySetupRow__stepIcon" aria-label="Done" />
                                    ) : step.skipped ? (
                                        <IconMinusSquare className="TodaySetupRow__stepIcon" aria-label="Skipped" />
                                    ) : (
                                        <IconCircleDashed className="TodaySetupRow__stepIcon" aria-hidden />
                                    )}
                                    <span>{step.skipped ? 'GitHub skipped' : STEP_NAMES[step.key]}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                    <div className="TodayRow__end">
                        <div className="TodayRow__actions">
                            <Tooltip>
                                <TooltipTrigger
                                    render={
                                        <Button
                                            variant="link-muted"
                                            size="icon-sm"
                                            aria-label="Hide this guide"
                                            onClick={hideGuide}
                                            data-attr="today-get-started-row-hide"
                                        />
                                    }
                                >
                                    <IconHide className="size-3.5" />
                                </TooltipTrigger>
                                <TooltipContent side="bottom">Hide this guide</TooltipContent>
                            </Tooltip>
                        </div>
                        <IconChevronRight className="TodayRow__arrow" aria-hidden />
                    </div>
                </li>
            </ol>
            <Dialog open={guideOpen} onOpenChange={(open: boolean) => (open ? openGuide() : closeGuide())}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Set up PostHog</DialogTitle>
                        <DialogDescription>
                            <span translate="no">{`${doneCount} of ${steps.length} steps done`}</span>
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <TodayGetStarted />
                    </DialogBody>
                    <DialogFooter className="sm:justify-between">
                        <Button variant="link-muted" onClick={hideGuide} data-attr="today-get-started-hide">
                            Hide this guide
                        </Button>
                        <Button variant="outline" onClick={closeGuide} data-attr="today-get-started-close">
                            Close
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}
