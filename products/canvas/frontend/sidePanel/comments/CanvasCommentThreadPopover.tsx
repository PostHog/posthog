import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { cn } from '@posthog/quill'

import { canvasCommentsLogic } from './canvasCommentsLogic'
import { CanvasCommentThreadCard } from './CanvasCommentThreadCard'

const POPOVER_WIDTH_PX = 320
const POPOVER_MAX_HEIGHT_PX = 480
const POPOVER_GAP_PX = 6
const VIEWPORT_MARGIN_PX = 8

export function CanvasCommentThreadPopover(): JSX.Element | null {
    const { activeThreadId, activeThreadRect, threads } = useValues(canvasCommentsLogic)
    const { setActiveThread } = useActions(canvasCommentsLogic)
    const ref = useRef<HTMLDivElement>(null)
    const thread = threads?.find((candidate) => candidate.root.id === activeThreadId) ?? null
    const open = !!thread

    useEffect(() => {
        if (!open) {
            return
        }
        ref.current?.focus({ preventScroll: true })
        const close = (): void => setActiveThread(null)
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                close()
            }
        }
        const onPointerDown = (event: PointerEvent): void => {
            const target = event.target
            if (
                target instanceof Element &&
                (ref.current?.contains(target) ||
                    target.closest('[data-quill-portal], [data-attr="canvas-comments-menu"]'))
            ) {
                return
            }
            close()
        }
        window.addEventListener('keydown', onKeyDown)
        window.addEventListener('blur', close)
        window.addEventListener('resize', close)
        document.addEventListener('pointerdown', onPointerDown)
        return () => {
            window.removeEventListener('keydown', onKeyDown)
            window.removeEventListener('blur', close)
            window.removeEventListener('resize', close)
            document.removeEventListener('pointerdown', onPointerDown)
        }
    }, [open, activeThreadId, setActiveThread])

    if (!thread) {
        return null
    }

    let position: React.CSSProperties | undefined
    if (activeThreadRect) {
        const width = Math.min(POPOVER_WIDTH_PX, window.innerWidth - VIEWPORT_MARGIN_PX * 2)
        const left = Math.max(
            VIEWPORT_MARGIN_PX,
            Math.min(activeThreadRect.left, window.innerWidth - width - VIEWPORT_MARGIN_PX)
        )
        const spaceBelow = window.innerHeight - activeThreadRect.bottom
        position =
            spaceBelow < POPOVER_MAX_HEIGHT_PX && activeThreadRect.top > spaceBelow
                ? { left, width, bottom: window.innerHeight - activeThreadRect.top + POPOVER_GAP_PX }
                : { left, width, top: activeThreadRect.bottom + POPOVER_GAP_PX }
    }

    return (
        <div
            ref={ref}
            data-quill
            role="dialog"
            aria-label="Comment thread"
            tabIndex={-1}
            className={cn(
                'z-50 flex max-h-[min(480px,calc(100%-24px))] flex-col overflow-hidden rounded-lg border border-border bg-background shadow-lg outline-none',
                position
                    ? 'fixed max-h-[min(480px,calc(100vh-16px))]'
                    : 'absolute top-3 right-3 w-80 max-w-[calc(100%-24px)]'
            )}
            style={position}
            data-attr="canvas-comment-thread-popover"
        >
            <CanvasCommentThreadCard thread={thread} />
        </div>
    )
}
