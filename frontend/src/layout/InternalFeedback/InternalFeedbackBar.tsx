import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconCursorClick, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconDragHandle } from 'lib/lemon-ui/icons'

import { clampToViewport, internalFeedbackLogic } from './internalFeedbackLogic'

export function InternalFeedbackBar(): JSX.Element {
    const { position, isInspecting } = useValues(internalFeedbackLogic)
    const { setPosition, startInspecting, stopInspecting, hide } = useActions(internalFeedbackLogic)
    const barRef = useRef<HTMLDivElement>(null)
    const dragOffset = useRef<{ x: number; y: number } | null>(null)

    const viewport = { width: window.innerWidth, height: window.innerHeight }
    const size = barRef.current
        ? { width: barRef.current.offsetWidth, height: barRef.current.offsetHeight }
        : { width: 0, height: 0 }
    const placed = position ? clampToViewport(position, size, viewport) : null

    return (
        <div
            ref={barRef}
            className={`fixed z-[2147483647] pointer-events-auto flex items-center gap-1 p-1 rounded-lg border border-primary bg-surface-primary shadow-lg ${
                placed ? '' : 'bottom-4 left-1/2 -translate-x-1/2'
            }`}
            // eslint-disable-next-line react/forbid-dom-props
            style={placed ? { left: placed.x, top: placed.y } : undefined}
        >
            <button
                type="button"
                aria-label="Move the feedback bar"
                className="flex items-center self-stretch px-0.5 text-secondary cursor-grab active:cursor-grabbing touch-none bg-transparent border-none"
                onPointerDown={(e) => {
                    if (!barRef.current) {
                        return
                    }
                    const rect = barRef.current.getBoundingClientRect()
                    dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
                    e.currentTarget.setPointerCapture(e.pointerId)
                }}
                onPointerMove={(e) => {
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
            >
                <IconDragHandle className="text-lg" />
            </button>
            <LemonButton
                size="small"
                type={isInspecting ? 'primary' : 'secondary'}
                icon={<IconCursorClick />}
                onClick={() => (isInspecting ? stopInspecting() : startInspecting())}
                data-attr="internal-feedback-inspect"
            >
                Inspect
            </LemonButton>
            <LemonButton size="small" icon={<IconX />} onClick={() => hide()} data-attr="internal-feedback-close">
                Close
            </LemonButton>
        </div>
    )
}
