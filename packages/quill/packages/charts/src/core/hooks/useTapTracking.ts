import type { MutableRefObject } from 'react'
import React, { useCallback, useRef } from 'react'

import { useLatest } from './useLatest'

export interface TapTracking {
    lastPointerTypeRef: MutableRefObject<string>
    /** The `dataIndex` of the tooltip that was visible when the gesture started, or -1. */
    tapDownTooltipIndexRef: MutableRefObject<number>
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void
}

// Touch devices fire no mousemove before a tap, so a click handler has to resolve the tapped
// point itself and needs to know whether the click came from a touch. Both refs are captured at
// pointerdown because a tap's compatibility mouse events fire after pointerup, so by click time
// the tooltip may already reflect this very tap. Read the visible tooltip, not the hover: hover
// can outlive a tooltip that was just hidden.
export function useTapTracking(tooltipCtx: { dataIndex: number } | null): TapTracking {
    const tooltipCtxRef = useLatest(tooltipCtx)
    const lastPointerTypeRef = useRef<string>('mouse')
    const tapDownTooltipIndexRef = useRef<number>(-1)

    const onPointerDown = useCallback(
        (e: React.PointerEvent<HTMLDivElement>) => {
            lastPointerTypeRef.current = e.pointerType
            tapDownTooltipIndexRef.current = tooltipCtxRef.current?.dataIndex ?? -1
        },
        [tooltipCtxRef]
    )

    return { lastPointerTypeRef, tapDownTooltipIndexRef, onPointerDown }
}
