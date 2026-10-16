import { useCallback, useEffect, useRef } from 'react'
import type { MutableRefObject } from 'react'

import { isPointInSafeTriangle } from 'lib/ui/Menus/safeTriangle'
import type { Point } from 'lib/ui/Menus/safeTriangle'

const HOVER_STALL_MS = 400

export function useAnnotationPopoverHover(onLeave: () => void): {
    popupRef: MutableRefObject<HTMLDivElement | null>
    start: (point: Point) => void
    cancel: () => void
    leavePopup: () => void
} {
    const popupRef = useRef<HTMLDivElement | null>(null)
    const anchorRef = useRef<Point | null>(null)
    const timeoutRef = useRef<number | null>(null)
    const mouseMoveRef = useRef<((event: MouseEvent) => void) | null>(null)

    const cancel = useCallback((): void => {
        if (timeoutRef.current !== null) {
            window.clearTimeout(timeoutRef.current)
            timeoutRef.current = null
        }
        if (mouseMoveRef.current) {
            document.removeEventListener('mousemove', mouseMoveRef.current)
            mouseMoveRef.current = null
        }
        anchorRef.current = null
    }, [])

    const leavePopup = useCallback((): void => {
        cancel()
        onLeave()
    }, [cancel, onLeave])

    const start = useCallback(
        (point: Point): void => {
            cancel()
            anchorRef.current = point

            const scheduleClose = (): void => {
                if (timeoutRef.current !== null) {
                    window.clearTimeout(timeoutRef.current)
                }
                timeoutRef.current = window.setTimeout(leavePopup, HOVER_STALL_MS)
            }

            const onMouseMove = (event: MouseEvent): void => {
                const popup = popupRef.current
                const anchor = anchorRef.current
                if (popup?.contains(event.target as Node)) {
                    cancel()
                } else if (
                    !popup ||
                    (anchor &&
                        isPointInSafeTriangle(
                            { x: event.clientX, y: event.clientY },
                            anchor,
                            popup.getBoundingClientRect()
                        ))
                ) {
                    scheduleClose()
                } else {
                    leavePopup()
                }
            }

            mouseMoveRef.current = onMouseMove
            document.addEventListener('mousemove', onMouseMove)
            scheduleClose()
        },
        [cancel, leavePopup]
    )

    useEffect(() => cancel, [cancel])

    return { popupRef, start, cancel, leavePopup }
}
