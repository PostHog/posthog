import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconSparkles, IconX } from '@posthog/icons'
import { Button, PopoverTrigger, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { TodayLauncherAlign, todayContextPanelLogic } from './todayContextPanelLogic'

const DRAG_THRESHOLD = 5

const ALIGNS: TodayLauncherAlign[] = ['start', 'center', 'end']

const JUSTIFY_CLASSES: Record<TodayLauncherAlign, string> = {
    start: 'justify-start',
    center: 'justify-center',
    end: 'justify-end',
}

const ZONE_CLASSES: Record<TodayLauncherAlign, string> = {
    start: 'left-0',
    center: 'left-1/2 -translate-x-1/2',
    end: 'right-0',
}

interface LauncherDrag {
    dx: number
    dy: number
    nearest: TodayLauncherAlign
}

/** The zones sit side by side along one edge, so the closest one is whichever third of the edge the button is over. */
function nearestAlign(host: DOMRect, centerX: number): TodayLauncherAlign {
    const third = Math.min(Math.max(Math.floor(((centerX - host.left) / host.width) * 3), 0), 2)
    return ALIGNS[third]
}

export function TodayContextPanelLauncher(): JSX.Element {
    const { launcherAlign, launcherHidden, floatingOpen } = useValues(todayContextPanelLogic)
    const { setLauncherAlign, hideLauncher } = useActions(todayContextPanelLogic)
    const hostRef = useRef<HTMLDivElement>(null)
    // Set when a press turned into a drag, so the click that ends it doesn't also open the panel.
    const draggedRef = useRef(false)
    const [drag, setDrag] = useState<LauncherDrag | null>(null)
    // Ends an active drag. A release outside the window never reaches the listeners, so blur and unmount call this.
    const stopDragRef = useRef<(() => void) | null>(null)

    useEffect(() => () => stopDragRef.current?.(), [])

    const startDrag = (event: React.PointerEvent<HTMLSpanElement>): void => {
        draggedRef.current = false
        const host = hostRef.current?.getBoundingClientRect()
        if (event.button !== 0 || !host || (event.target as HTMLElement).closest('[data-launcher-close]')) {
            return
        }
        const start = { x: event.clientX, y: event.clientY }
        const button = event.currentTarget.getBoundingClientRect()
        const originX = button.left + button.width / 2
        const nearest = (clientX: number): TodayLauncherAlign => nearestAlign(host, originX + clientX - start.x)

        const move = (moveEvent: PointerEvent): void => {
            const dx = moveEvent.clientX - start.x
            const dy = moveEvent.clientY - start.y
            if (!draggedRef.current && Math.hypot(dx, dy) < DRAG_THRESHOLD) {
                return
            }
            draggedRef.current = true
            setDrag({ dx, dy, nearest: nearest(moveEvent.clientX) })
        }
        const stop = (): void => {
            window.removeEventListener('pointermove', move)
            window.removeEventListener('pointerup', end)
            window.removeEventListener('pointercancel', end)
            window.removeEventListener('blur', cancel)
            stopDragRef.current = null
            setDrag(null)
        }
        const end = (endEvent: PointerEvent): void => {
            const align = nearest(endEvent.clientX)
            if (draggedRef.current && endEvent.type === 'pointerup' && align !== launcherAlign) {
                setLauncherAlign(align)
            }
            stop()
        }
        // A cancelled drag leaves the button where it was, and no click follows to swallow.
        const cancel = (): void => {
            draggedRef.current = false
            stop()
        }

        // Window listeners, not pointer capture: capture would retarget the closing click away from the button.
        window.addEventListener('pointermove', move)
        window.addEventListener('pointerup', end)
        window.addEventListener('pointercancel', end)
        window.addEventListener('blur', cancel)
        stopDragRef.current = cancel
    }

    return (
        // Stays mounted while docked, so the button can sink away and rise back with the panel. Scenes without
        // PostHog AI, like a canvas, hide it but keep the host for other undocked tabs.
        <div
            ref={hostRef}
            data-quill
            className={cn(
                'TodayContextPanelButton pointer-events-none absolute inset-x-4 bottom-4 z-[var(--z-main-nav)] flex',
                JUSTIFY_CLASSES[launcherAlign]
            )}
            data-hidden={launcherHidden || undefined}
            {...(launcherHidden ? { inert: '' } : {})}
        >
            {drag &&
                ALIGNS.map((align) => (
                    <div
                        key={align}
                        aria-hidden
                        className={cn(
                            'absolute bottom-0 h-7 w-24 rounded-full border border-dashed border-ring transition-opacity',
                            ZONE_CLASSES[align],
                            align === drag.nearest ? 'bg-[var(--fill-hover)] opacity-100' : 'opacity-40'
                        )}
                    />
                ))}
            {/* The outline button is see-through, so an opaque pill sits behind it over the page. */}
            <span
                className="group/launcher pointer-events-auto relative touch-none rounded-full bg-background shadow-md select-none data-[dragging]:cursor-grabbing data-[dragging]:shadow-lg"
                data-dragging={drag ? '' : undefined}
                onPointerDown={startDrag}
                onClickCapture={(event) => {
                    if (draggedRef.current) {
                        event.stopPropagation()
                        draggedRef.current = false
                    }
                }}
                // The drag offset changes on every pointer move, which a class can't express.
                // eslint-disable-next-line react/forbid-dom-props
                style={drag ? { translate: `${drag.dx}px ${drag.dy}px` } : undefined}
            >
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <PopoverTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        size="default"
                                        aria-label="Ask PostHog AI"
                                        className="w-24 justify-center rounded-full"
                                        data-attr="today-ai-chat-button"
                                    />
                                }
                            />
                        }
                    >
                        <IconSparkles />
                    </TooltipTrigger>
                    {!drag && <TooltipContent side="top">Ask PostHog AI</TooltipContent>}
                </Tooltip>
                {/* Hiding the button while its card is open would leave the card without an anchor. */}
                {!floatingOpen && (
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Button
                                    size="icon-xs"
                                    aria-label="Dismiss floating button"
                                    className="absolute top-1/2 right-1 -translate-y-1/2 rounded-full text-muted-foreground opacity-0 group-hover/launcher:opacity-100 group-has-[:focus-visible]/launcher:opacity-100 group-data-[dragging]/launcher:opacity-0 hover:text-foreground"
                                    data-launcher-close
                                    data-attr="today-ai-chat-button-hide"
                                    onClick={() => hideLauncher()}
                                />
                            }
                        >
                            <IconX />
                        </TooltipTrigger>
                        <TooltipContent side="top">Dismiss floating button</TooltipContent>
                    </Tooltip>
                )}
            </span>
        </div>
    )
}
