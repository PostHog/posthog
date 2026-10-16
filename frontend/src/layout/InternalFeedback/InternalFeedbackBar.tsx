import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconCursorClick, IconDrag, IconMessage, IconX } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { INTERNAL_FEEDBACK_IGNORE_ATTR } from './captureFeedbackScreenshot'
import { clampToViewport, internalFeedbackLogic } from './internalFeedbackLogic'

export function InternalFeedbackBar(): JSX.Element {
    const { position, isInspecting, target, justSent } = useValues(internalFeedbackLogic)
    const { setPosition, startInspecting, stopInspecting, startGeneralFeedback, clearSelection, hide } =
        useActions(internalFeedbackLogic)
    const barRef = useRef<HTMLDivElement>(null)
    const dragOffset = useRef<{ x: number; y: number } | null>(null)

    // The tooltips explain the bar while it is idle. Once a flow is open they only get in the way.
    const tooltipsDisabled = isInspecting || !!target
    const isGeneralFeedbackOpen = !!target && !target.element

    const viewport = { width: window.innerWidth, height: window.innerHeight }
    const size = barRef.current
        ? { width: barRef.current.offsetWidth, height: barRef.current.offsetHeight }
        : { width: 0, height: 0 }
    const placed = position ? clampToViewport(position, size, viewport) : null

    return (
        <div
            ref={barRef}
            data-quill
            {...{ [INTERNAL_FEEDBACK_IGNORE_ATTR]: '' }}
            // Above every other layer, including modals and tooltips, so the bar never ends up hidden.
            className={cn(
                'fixed z-[2147483647] pointer-events-auto flex items-center gap-1 p-1 rounded-lg border border-border bg-card text-card-foreground shadow-md',
                !placed && 'bottom-4 left-1/2 -translate-x-1/2'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={placed ? { left: placed.x, top: placed.y } : undefined}
        >
            <Tooltip disabled={tooltipsDisabled}>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon"
                            aria-label="Drag to move the feedback bar"
                            className="cursor-grab touch-none active:cursor-grabbing"
                            onPointerDown={(e: React.PointerEvent<HTMLButtonElement>) => {
                                if (!barRef.current) {
                                    return
                                }
                                const rect = barRef.current.getBoundingClientRect()
                                dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
                                e.currentTarget.setPointerCapture(e.pointerId)
                            }}
                            onPointerMove={(e: React.PointerEvent<HTMLButtonElement>) => {
                                if (!dragOffset.current || !barRef.current) {
                                    return
                                }
                                setPosition(
                                    clampToViewport(
                                        { x: e.clientX - dragOffset.current.x, y: e.clientY - dragOffset.current.y },
                                        { width: barRef.current.offsetWidth, height: barRef.current.offsetHeight },
                                        { width: window.innerWidth, height: window.innerHeight }
                                    )
                                )
                            }}
                            onPointerUp={() => {
                                dragOffset.current = null
                            }}
                            onPointerCancel={() => {
                                dragOffset.current = null
                            }}
                        />
                    }
                >
                    <IconDrag />
                </TooltipTrigger>
                <TooltipContent>Drag to move the feedback bar</TooltipContent>
            </Tooltip>
            <Tooltip disabled={tooltipsDisabled}>
                <TooltipTrigger
                    render={
                        <Button
                            aria-pressed={isInspecting}
                            className={cn(isInspecting && 'bg-fill-selected')}
                            onClick={() => (isInspecting ? stopInspecting() : startInspecting())}
                            data-attr="internal-feedback-inspect"
                        />
                    }
                >
                    <IconCursorClick />
                    Inspect
                </TooltipTrigger>
                <TooltipContent>Click to pick a part of the page and send feedback about it to the devs</TooltipContent>
            </Tooltip>
            <Tooltip disabled={tooltipsDisabled}>
                <TooltipTrigger
                    render={
                        <Button
                            aria-pressed={isGeneralFeedbackOpen}
                            className={cn(isGeneralFeedbackOpen && 'bg-fill-selected')}
                            onClick={() => (isGeneralFeedbackOpen ? clearSelection() : startGeneralFeedback())}
                            data-attr="internal-feedback-general"
                        />
                    }
                >
                    <IconMessage />
                    General feedback
                </TooltipTrigger>
                <TooltipContent>Click to send feedback about this whole page, with a screenshot of it</TooltipContent>
            </Tooltip>
            <Tooltip disabled={tooltipsDisabled}>
                <TooltipTrigger render={<Button onClick={() => hide()} data-attr="internal-feedback-close" />}>
                    <IconX />
                    Close
                </TooltipTrigger>
                <TooltipContent>Click to hide this bar. It comes back when you reload the page.</TooltipContent>
            </Tooltip>
            {justSent && (
                <Text size="xs" variant="muted" render={<span />} className="pr-2" role="status">
                    Sent, thanks!
                </Text>
            )}
        </div>
    )
}
