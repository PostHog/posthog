import { useCallback, useEffect, useMemo, useRef } from 'react'

import { isPointInSafeTriangle, Point } from './safeTriangle'

/** A pointer that pauses this long is no longer travelling to the submenu, whatever the wedge says. */
const MAX_STALL_MS = 200

export interface SubmenuSafeTriangle {
    /** Attach to `Menu.SubmenuTrigger`. */
    triggerRef: (element: HTMLElement | null) => void
    /** Attach to the submenu's `Menu.Popup`. */
    popupRef: (element: HTMLElement | null) => void
}

/**
 * Keeps a submenu open while the pointer travels diagonally from its trigger to the submenu itself.
 *
 * Base UI only does this for submenus that open on hover; one that opens on click closes as soon as
 * the pointer grazes another item of the parent menu, which is most of the diagonal path. Blocking
 * the mouse move before it reaches those items keeps the path from registering as a hover.
 */
export function useSubmenuSafeTriangle(): SubmenuSafeTriangle {
    const triggerElement = useRef<HTMLElement | null>(null)
    const popupElement = useRef<HTMLElement | null>(null)
    const anchor = useRef<{ point: Point; movedAt: number } | null>(null)
    const detach = useRef<(() => void) | null>(null)

    const handleMouseMove = useCallback((event: MouseEvent): void => {
        const trigger = triggerElement.current
        const popup = popupElement.current
        if (!trigger || !popup) {
            return
        }

        const point = { x: event.clientX, y: event.clientY }
        // Going by the event target rather than the trigger's rect matters on the boundary pixel,
        // which reads as inside the rect while the move already belongs to the item below.
        if (trigger.contains(event.target as Node)) {
            // The last point the pointer held on the trigger is where the wedge starts.
            anchor.current = { point, movedAt: event.timeStamp }
            return
        }

        const from = anchor.current
        if (!from) {
            return
        }
        if (
            event.timeStamp - from.movedAt < MAX_STALL_MS &&
            isPointInSafeTriangle(point, from.point, popup.getBoundingClientRect())
        ) {
            from.movedAt = event.timeStamp
            event.stopPropagation()
            return
        }
        anchor.current = null
    }, [])

    // Listening on the parent menu rather than the document keeps every other mouse move untouched.
    const listenOnParentMenu = useCallback((): void => {
        detach.current?.()
        detach.current = null
        anchor.current = null

        const parentMenu = popupElement.current ? triggerElement.current?.closest<HTMLElement>('[role="menu"]') : null
        if (!parentMenu) {
            return
        }
        parentMenu.addEventListener('mousemove', handleMouseMove, true)
        detach.current = () => parentMenu.removeEventListener('mousemove', handleMouseMove, true)
    }, [handleMouseMove])

    useEffect(() => () => detach.current?.(), [])

    return useMemo(
        () => ({
            triggerRef: (element: HTMLElement | null): void => {
                triggerElement.current = element
                listenOnParentMenu()
            },
            popupRef: (element: HTMLElement | null): void => {
                popupElement.current = element
                listenOnParentMenu()
            },
        }),
        [listenOnParentMenu]
    )
}
