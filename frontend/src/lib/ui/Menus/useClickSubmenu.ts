import { Menu } from '@base-ui/react/menu'
import { MouseEvent as ReactMouseEvent, RefCallback, useCallback, useEffect, useMemo, useRef } from 'react'

import { isPointInSafeTriangle, Point } from './isPointInSafeTriangle'

/** A pointer that pauses this long on the way is no longer travelling to the submenu. */
export const SUBMENU_TRAVEL_STALL_MS = 200

export interface ClickSubmenuProps {
    rootProps: Pick<Menu.SubmenuRoot.Props, 'onOpenChange'>
    triggerProps: Pick<Menu.SubmenuTrigger.Props, 'openOnHover' | 'onMouseLeave'>
    popupProps: { ref: RefCallback<HTMLDivElement> }
}

interface Travel {
    anchor: Point
    lastMoveAt: number
}

/**
 * Props for a Base UI submenu that opens on click.
 *
 * Base UI only protects hover-opened submenus with a safe polygon. A click-opened one closes as soon as the
 * pointer grazes a sibling item on its way to the submenu, and a repeat click on the trigger toggles it closed.
 * While the pointer travels through the triangle from where it left the trigger to the submenu, this hook stops
 * mouse moves before they reach the parent menu's items. Leaving the triangle or stalling hands control back.
 */
export function useClickSubmenu(): ClickSubmenuProps {
    const popupElement = useRef<HTMLDivElement | null>(null)
    const travel = useRef<Travel | null>(null)

    const handleDocumentMouseMove = useCallback((event: MouseEvent): void => {
        const popup = popupElement.current
        const current = travel.current
        const now = performance.now()
        const point = { x: event.clientX, y: event.clientY }
        const stalled = current !== null && now - current.lastMoveAt > SUBMENU_TRAVEL_STALL_MS
        if (
            !popup ||
            !current ||
            stalled ||
            !isPointInSafeTriangle(point, current.anchor, popup.getBoundingClientRect())
        ) {
            document.removeEventListener('mousemove', handleDocumentMouseMove, true)
            travel.current = null
            return
        }
        current.lastMoveAt = now
        event.stopPropagation()
    }, [])

    const handleTriggerMouseLeave = useCallback(
        (event: ReactMouseEvent<HTMLElement>): void => {
            travel.current = { anchor: { x: event.clientX, y: event.clientY }, lastMoveAt: performance.now() }
            document.addEventListener('mousemove', handleDocumentMouseMove, true)
        },
        [handleDocumentMouseMove]
    )

    const handleOpenChange = useCallback((open: boolean, details: Menu.SubmenuRoot.ChangeEventDetails): void => {
        // Keep the submenu open on a repeat click of its trigger, like native menus do.
        if (!open && details.reason === 'trigger-press') {
            details.cancel()
        }
    }, [])

    const setPopupElement = useCallback<RefCallback<HTMLDivElement>>((element) => {
        popupElement.current = element
    }, [])

    useEffect(
        () => () => document.removeEventListener('mousemove', handleDocumentMouseMove, true),
        [handleDocumentMouseMove]
    )

    return useMemo(
        () => ({
            rootProps: { onOpenChange: handleOpenChange },
            triggerProps: { openOnHover: false, onMouseLeave: handleTriggerMouseLeave },
            popupProps: { ref: setPopupElement },
        }),
        [handleOpenChange, handleTriggerMouseLeave, setPopupElement]
    )
}
