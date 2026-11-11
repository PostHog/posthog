import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Popover, PopoverContent } from '@posthog/quill'

import { SidePanelTab } from '~/types'

import { TodayContextPanelCard } from './TodayContextPanelCard'
import { TodayContextPanelLauncher } from './TodayContextPanelLauncher'
import {
    TODAY_CONTEXT_PANEL_DOCK_EDGE,
    TODAY_SIDE_PANEL_DEFAULT_WIDTH,
    todayContextPanelLogic,
} from './todayContextPanelLogic'

/** Presses on these inside the header act on them instead of moving the panel. */
const NOT_A_DRAG_HANDLE = 'button, a, input, [role="menuitem"]'

export function TodayContextPanelFloating(): JSX.Element {
    const { floatingOpen, floatingOffset, floatingActiveTab, dockHint, launcherAlign } =
        useValues(todayContextPanelLogic)
    const { setFloatingOpen, setFloatingTab, setFloatingOffset, setDockHint, dock } = useActions(todayContextPanelLogic)
    const cardRef = useRef<HTMLDivElement>(null)

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
                <TodayContextPanelLauncher />
                <PopoverContent
                    side="top"
                    align={launcherAlign}
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
                    className="pointer-events-none fixed top-10 right-1 bottom-1 z-[var(--z-layout-panel)] rounded-lg border border-dashed border-ring bg-[var(--fill-hover)] opacity-60"
                    // The docked panel's default width, less its own inset, so the outline shows where the card lands.
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `calc(${TODAY_SIDE_PANEL_DEFAULT_WIDTH}px - 0.5rem)` }}
                />
            )}
        </>
    )
}
