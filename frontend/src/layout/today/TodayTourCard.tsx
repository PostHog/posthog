import { useActions } from 'kea'
import { MutableRefObject, useEffect, useMemo, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'
import {
    Button,
    Card,
    CardAction,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Popover,
    PopoverContent,
    Text,
    useReducedMotion,
} from '@posthog/quill'

import { TodayTourPoint } from './todayTourGeometry'
import { TODAY_TOUR_STEPS, TodayTourStep, todayTourLogic } from './todayTourLogic'
import { TodayTourTimer } from './TodayTourTimer'

const TOUR_STEP_MS = 8000
// The card sits to the right of the cursor's tip, clear of the arrow, with its top a little above the tip.
const CURSOR_GAP_X_PX = 32
const CURSOR_LIFT_PX = 20

interface TodayTourCardProps {
    step: TodayTourStep
    stepIndex: number
    /** The cursor's tip. The card shows beside it, and grows out of it. */
    anchor: TodayTourPoint
    /** Survives the card, which is remounted for each step, so keyboard focus can return to Next. */
    refocusNextRef: MutableRefObject<boolean>
}

/** One step of the tour, next to the tour's cursor. It moves on by itself on a timer, paused while hovered. */
export function TodayTourCard({ step, stepIndex, anchor, refocusNextRef }: TodayTourCardProps): JSX.Element {
    const { nextTourStep, endTour } = useActions(todayTourLogic)
    // Moving the whole page on a timer is the kind of motion this setting asks to avoid, so the tour waits for Next.
    const reducedMotion = useReducedMotion()
    const [open, setOpen] = useState(false)
    const [hovered, setHovered] = useState(false)
    const [focused, setFocused] = useState(false)
    // What runs once the card has finished leaving. The page changes behind an empty space, not under the card.
    const afterLeaveRef = useRef<(() => void) | null>(null)
    const nextButtonRef = useRef<HTMLButtonElement>(null)
    const virtualAnchor = useMemo(
        () => ({ getBoundingClientRect: () => DOMRect.fromRect({ x: anchor.x, y: anchor.y, width: 0, height: 0 }) }),
        [anchor]
    )

    // A popover that mounts open skips its entrance, so it mounts closed and opens straight after.
    useEffect(() => setOpen(true), [])

    const leaveThen = (next: () => void): void => {
        if (afterLeaveRef.current) {
            return
        }
        afterLeaveRef.current = next
        setOpen(false)
    }

    const goNext = (): void => {
        refocusNextRef.current = focused
        leaveThen(nextTourStep)
    }

    return (
        <Popover
            open={open}
            // The card stays until Next, the close button, the timer or Escape. A click elsewhere on the page is fine.
            onOpenChange={(nextOpen, { reason }) => {
                if (!nextOpen && reason === 'escape-key') {
                    leaveThen(endTour)
                }
            }}
            onOpenChangeComplete={(isOpen) => {
                if (!isOpen) {
                    afterLeaveRef.current?.()
                }
            }}
        >
            <PopoverContent
                anchor={virtualAnchor}
                side="right"
                align="start"
                sideOffset={CURSOR_GAP_X_PX}
                alignOffset={-CURSOR_LIFT_PX}
                // Focus stays where it was, such as on the menu row the last step points at, unless Next had it.
                initialFocus={() => {
                    const refocus = refocusNextRef.current
                    refocusNextRef.current = false
                    return refocus ? nextButtonRef.current : false
                }}
                finalFocus={false}
                aria-labelledby="today-tour-title"
                aria-describedby="today-tour-description"
                // The card draws the surface, so the popover only places and animates it.
                className="w-80 gap-0 border-0 bg-transparent p-0 shadow-none"
                data-attr="today-tour-popover"
                onMouseEnter={() => setHovered(true)}
                onMouseLeave={() => setHovered(false)}
                // Only keyboard focus pauses. A clicked Next keeps focus, which would otherwise pause every later step.
                onFocus={(event) => setFocused(event.target.matches(':focus-visible'))}
                onBlur={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                        setFocused(false)
                    }
                }}
            >
                {/* The same border and shadow as a quill popover. The card's own edge is a faint ring that a shadow class would replace. */}
                <Card className="border border-[var(--border)] shadow-[var(--shadow-md)]">
                    <CardHeader>
                        <CardTitle id="today-tour-title">{step.title}</CardTitle>
                        <CardDescription id="today-tour-description">{step.description}</CardDescription>
                        <CardAction>
                            <Button
                                size="icon-sm"
                                aria-label="End tour"
                                onClick={() => leaveThen(endTour)}
                                data-attr="today-tour-end"
                            >
                                <IconX />
                            </Button>
                        </CardAction>
                    </CardHeader>
                    <CardFooter className="justify-between gap-2">
                        <Text size="xs" variant="muted">
                            {`${stepIndex + 1} of ${TODAY_TOUR_STEPS.length}`}
                        </Text>
                        <div className="flex items-center gap-2">
                            {!reducedMotion && (
                                <TodayTourTimer
                                    durationMs={TOUR_STEP_MS}
                                    paused={hovered || focused || !open}
                                    onDone={() => leaveThen(nextTourStep)}
                                />
                            )}
                            <Button ref={nextButtonRef} variant="primary" onClick={goNext} data-attr="today-tour-next">
                                {stepIndex === TODAY_TOUR_STEPS.length - 1 ? 'Done' : 'Next'}
                            </Button>
                        </div>
                    </CardFooter>
                </Card>
            </PopoverContent>
        </Popover>
    )
}
