import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconSparkles } from '@posthog/icons'
import {
    Button,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { SidePanelTab } from '~/types'

import { TodayContextPanelCard } from './TodayContextPanelCard'
import { TODAY_CONTEXT_PANEL_DOCK_EDGE, todayContextPanelLogic } from './todayContextPanelLogic'

/** Presses on these inside the header act on them instead of moving the panel. */
const NOT_A_DRAG_HANDLE = 'button, a, input, [role="menuitem"]'

export function TodayContextPanelFloating(): JSX.Element {
    const { floatingOpen, floatingOffset, floatingActiveTab, docked, dockHint, panelTabs } =
        useValues(todayContextPanelLogic)
    const { setFloatingOpen, setFloatingTab, setFloatingOffset, setDockHint, dock } = useActions(todayContextPanelLogic)
    const cardRef = useRef<HTMLDivElement>(null)
    const launcherHidden = docked || !panelTabs.includes(SidePanelTab.Max)

    const startDrag = (event: React.PointerEvent<HTMLDivElement>): void => {
        if (event.button !== 0 || (event.target as HTMLElement).closest(NOT_A_DRAG_HANDLE)) {
            return
        }
        event.preventDefault()
        const handle = event.currentTarget
        const origin = floatingOffset
        const start = { x: event.clientX, y: event.clientY }
        const nearDockEdge = (clientX: number): boolean => clientX >= window.innerWidth - TODAY_CONTEXT_PANEL_DOCK_EDGE
        // Keeps the whole card on screen, so the header stays in reach to drag it back.
        const card = cardRef.current?.getBoundingClientRect()
        const clamp = (delta: number, min: number, max: number): number => Math.min(Math.max(delta, min), max)

        const move = (moveEvent: PointerEvent): void => {
            let dx = moveEvent.clientX - start.x
            let dy = moveEvent.clientY - start.y
            if (card) {
                dx = clamp(dx, -card.left, window.innerWidth - card.right)
                dy = clamp(dy, -card.top, window.innerHeight - card.bottom)
            }
            setFloatingOffset({ x: origin.x + dx, y: origin.y + dy })
            setDockHint(nearDockEdge(moveEvent.clientX))
        }
        const end = (endEvent: PointerEvent): void => {
            handle.removeEventListener('pointermove', move)
            handle.removeEventListener('pointerup', end)
            handle.removeEventListener('pointercancel', end)
            if (endEvent.type === 'pointerup' && nearDockEdge(endEvent.clientX)) {
                // A docked panel that undocks comes back where it was picked up, not at the window edge.
                setFloatingOffset(origin)
                dock()
            } else {
                setDockHint(false)
            }
        }

        handle.setPointerCapture(event.pointerId)
        handle.addEventListener('pointermove', move)
        handle.addEventListener('pointerup', end)
        handle.addEventListener('pointercancel', end)
    }

    return (
        <>
            <Popover
                open={floatingOpen}
                onOpenChange={(open, details) => {
                    // The panel stays up while the user works on the page around it.
                    if (!open && (details.reason === 'outside-press' || details.reason === 'focus-out')) {
                        return
                    }
                    // The button is the way to PostHog AI. Over another tab it switches the card to chat instead of
                    // closing it, and it always opens on chat.
                    if (floatingActiveTab !== SidePanelTab.Max) {
                        setFloatingTab(SidePanelTab.Max)
                        if (!open && details.reason === 'trigger-press') {
                            return
                        }
                    }
                    setFloatingOpen(open)
                }}
            >
                {/* Stays mounted while docked, so the button can sink away and rise back with the panel. Scenes
                    without PostHog AI, like a canvas, hide it but keep the host for other undocked tabs. */}
                <div
                    data-quill
                    className="TodayContextPanelButton pointer-events-none absolute inset-x-0 bottom-4 z-[var(--z-main-nav)] flex justify-center"
                    data-hidden={launcherHidden || undefined}
                    {...(launcherHidden ? { inert: '' } : {})}
                >
                    {/* The outline button is see-through, so an opaque pill sits behind it over the page. */}
                    <span className="pointer-events-auto rounded-full bg-background shadow-md">
                        <Tooltip>
                            <TooltipTrigger
                                delay={0}
                                render={
                                    <PopoverTrigger
                                        render={
                                            <Button
                                                variant="outline"
                                                size="lg"
                                                aria-label="Ask PostHog AI"
                                                className="w-34 justify-center rounded-full"
                                                data-attr="today-ai-chat-button"
                                            />
                                        }
                                    />
                                }
                            >
                                <IconSparkles />
                            </TooltipTrigger>
                            <TooltipContent side="top">Ask PostHog AI</TooltipContent>
                        </Tooltip>
                    </span>
                </div>
                <PopoverContent
                    side="top"
                    sideOffset={8}
                    initialFocus={() =>
                        cardRef.current?.querySelector<HTMLElement>('textarea, [contenteditable="true"]') ?? true
                    }
                    className="w-auto gap-0 border-0 bg-transparent p-0 shadow-none"
                    // The drag offset changes on every pointer move, which a class can't express.
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ translate: `${floatingOffset.x}px ${floatingOffset.y}px` }}
                >
                    {/* Fixed size: the panels scroll inside, and a size that followed a streaming thread would jump. */}
                    <TodayContextPanelCard
                        ref={cardRef}
                        docked={false}
                        tab={floatingActiveTab}
                        onDragStart={startDrag}
                        className="h-[min(40rem,calc(100vh-10rem))] w-85 shadow-lg"
                    />
                </PopoverContent>
            </Popover>
            {dockHint && (
                <div
                    data-quill
                    aria-hidden
                    className="pointer-events-none fixed top-10 right-1 bottom-1 z-[var(--z-layout-panel)] w-[min(32rem,40vw)] rounded-lg border border-dashed border-ring bg-[var(--fill-hover)] opacity-60"
                />
            )}
        </>
    )
}
