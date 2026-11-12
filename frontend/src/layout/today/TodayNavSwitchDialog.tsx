import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Highlight,
    useReducedMotion,
} from '@posthog/quill'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { OLD_NAV_SUNSET, navSwitchLogic } from 'lib/components/NavSwitch/navSwitchLogic'

import conspiracyBoardHog from 'public/hedgehog/conspiracy-board-hog.png'

import { clickPoint } from './todayTourGeometry'
import { todayTourLogic } from './todayTourLogic'

/** Greets someone who just switched to the new navigation, with a tour and a way back. */
export function TodayNavSwitchDialog(): JSX.Element {
    const { newNavDialogOpen } = useValues(navSwitchLogic)
    const { setNewNavDialogOpen, switchNav, dismissNewNavDialog, newNavDialogClosed } = useActions(navSwitchLogic)
    const { tourCompleted, tourJustCompleted } = useValues(todayTourLogic)
    const { startTour } = useActions(todayTourLogic)
    const reducedMotion = useReducedMotion()
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti({ count: 60, power: 6, duration: 2500 })

    const tryItOut = (): void => {
        setNewNavDialogOpen(false)
        if (!reducedMotion) {
            // Three bursts in quick succession, each from its own random spot.
            for (const delay of [0, 250, 500]) {
                window.setTimeout(triggerHogfetti, delay)
            }
        }
    }

    return (
        <>
            <Dialog
                open={newNavDialogOpen}
                // The buttons close the dialog through the logic, so only a dismissal (the close button, Escape, a click
                // outside) reaches `onOpenChange`.
                onOpenChange={(open: boolean) => (open ? setNewNavDialogOpen(true) : dismissNewNavDialog())}
                // A dismissal's hint waits for the close to finish, so the dialog's focus return does not land in the menu.
                onOpenChangeComplete={(open: boolean) => !open && newNavDialogClosed()}
            >
                <DialogContent overlayClassName="TodayNavSwitchDialog__overlay" data-attr="today-nav-switch-dialog">
                    {tourJustCompleted ? (
                        <DialogHeader className="items-center gap-2 pt-6 text-center">
                            <DialogTitle className="text-xl tracking-tight">
                                Wow, you actually{' '}
                                <Highlight animate delay={200}>
                                    finished
                                </Highlight>{' '}
                                the tour
                            </DialogTitle>
                            <DialogDescription className="text-sm">You're ready to go.</DialogDescription>
                        </DialogHeader>
                    ) : (
                        <DialogHeader className="items-center gap-2 pt-6 text-center">
                            <DialogTitle className="text-xl tracking-tight">
                                PostHog is{' '}
                                <Highlight animate delay={200}>
                                    changing
                                </Highlight>
                            </DialogTitle>
                            <DialogDescription className="text-sm">
                                We've thought long and hard about how you use PostHog and it's time for a change.
                                <br />
                                It's all about framing.
                            </DialogDescription>
                        </DialogHeader>
                    )}
                    <div className="flex flex-col items-center gap-6 px-6 pb-6 text-center">
                        {/* No `@posthog/brand` hoggie has this art yet, so it ships as a local, size-optimized PNG. */}
                        <img
                            src={conspiracyBoardHog}
                            alt=""
                            width={720}
                            height={407}
                            decoding="async"
                            className="h-auto w-full"
                        />
                        {tourJustCompleted ? (
                            <p className="m-0 text-sm text-balance text-muted-foreground">
                                Feedback is welcome. We're listening.
                                <br />
                                To switch back to the old design, go to Settings &gt; Feature previews and turn off the
                                new design preview.
                            </p>
                        ) : (
                            <p className="m-0 text-sm text-balance text-muted-foreground">
                                It's still being ironed out, but we think you'll like it. You can switch back to the
                                older design until {OLD_NAV_SUNSET}, but we suggest you give it a try!
                            </p>
                        )}
                    </div>
                    <DialogFooter>
                        {!tourCompleted && (
                            <Button
                                variant="outline"
                                onClick={() => switchNav('new_nav_dialog')}
                                data-attr="today-nav-switch-dialog-switch-back"
                            >
                                Switch back
                            </Button>
                        )}
                        {tourCompleted ? (
                            <Button variant="primary" onClick={tryItOut} data-attr="today-nav-switch-dialog-try-it">
                                I'll try it out
                            </Button>
                        ) : (
                            <Button
                                variant="primary"
                                // The tour's cursor starts where this click happened.
                                onClick={(event) => startTour(clickPoint(event))}
                                data-attr="today-nav-switch-dialog-take-tour"
                            >
                                Take tour
                            </Button>
                        )}
                    </DialogFooter>
                </DialogContent>
            </Dialog>
            {/* Outside the dialog, so the confetti keeps falling after the dialog closes. */}
            <HogfettiComponent />
        </>
    )
}
