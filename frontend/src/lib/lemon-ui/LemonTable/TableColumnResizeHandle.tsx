import { useEffect, useRef } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'

const MIN_COLUMN_WIDTH = 80
const MAX_COLUMN_WIDTH = 1000
interface TableColumnResizeHandleProps {
    onResize: (width: number) => void
    onResizeStart?: (header: HTMLTableCellElement) => void
    onResizeEnd?: () => void
}

export function TableColumnResizeHandle({
    onResize,
    onResizeStart,
    onResizeEnd,
}: TableColumnResizeHandleProps): JSX.Element {
    const cleanupResizeRef = useRef<(() => void) | null>(null)

    useEffect(
        () => () => {
            cleanupResizeRef.current?.()
        },
        []
    )

    const startResize = (event: ReactMouseEvent<HTMLButtonElement>): void => {
        if (event.button !== 0) {
            return
        }
        event.preventDefault()
        event.stopPropagation()
        cleanupResizeRef.current?.()

        const header = event.currentTarget.closest('th')
        if (header) {
            onResizeStart?.(header)
        }
        const startWidth = header?.getBoundingClientRect().width || MIN_COLUMN_WIDTH
        const startX = event.clientX
        let latestX = startX
        let didResize = false
        let animationFrame: number | null = null

        const applyResize = (): void => {
            animationFrame = null
            onResize(Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, startWidth + latestX - startX)))
        }
        const onMouseMove = (moveEvent: MouseEvent): void => {
            latestX = moveEvent.clientX
            didResize ||= latestX !== startX
            if (animationFrame === null) {
                animationFrame = requestAnimationFrame(applyResize)
            }
        }
        const cleanup = (): void => {
            window.removeEventListener('mousemove', onMouseMove)
            window.removeEventListener('mouseup', onMouseUp)
            document.body.classList.remove('is-resizing-column')
            cleanupResizeRef.current = null
        }
        const onMouseUp = (): void => {
            if (animationFrame !== null) {
                cancelAnimationFrame(animationFrame)
                applyResize()
            }
            if (didResize) {
                onResizeEnd?.()
            }
            cleanup()
        }

        cleanupResizeRef.current = cleanup
        window.addEventListener('mousemove', onMouseMove)
        window.addEventListener('mouseup', onMouseUp)
        document.body.classList.add('is-resizing-column')
    }

    return (
        <button
            type="button"
            className="absolute top-0 right-0 h-full w-2 translate-x-1/2 cursor-col-resize border-0 bg-transparent p-0 after:absolute after:inset-y-1/4 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-border hover:bg-primary-highlight focus-visible:bg-primary-highlight focus-visible:outline-none"
            aria-label="Resize column"
            onClick={(event) => event.stopPropagation()}
            onMouseDown={startResize}
        />
    )
}
