import { useCallback, useEffect, useRef, useState } from 'react'

import type { TooltipContext } from '../../types'

export function useTooltipState(): {
    tooltipContext: TooltipContext | null
    showTooltip: (context: TooltipContext) => void
    hideTooltip: () => void
} {
    const [tooltipContext, setTooltipContext] = useState<TooltipContext | null>(null)
    const hideTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const showTooltip = useCallback((ctx: TooltipContext) => {
        if (hideTimeoutRef.current) {
            clearTimeout(hideTimeoutRef.current)
            hideTimeoutRef.current = null
        }
        setTooltipContext(ctx)
    }, [])

    const hideTooltip = useCallback(() => {
        hideTimeoutRef.current = setTimeout(() => {
            setTooltipContext(null)
        }, 100)
    }, [])

    useEffect(() => {
        return () => {
            if (hideTimeoutRef.current) {
                clearTimeout(hideTimeoutRef.current)
            }
        }
    }, [])

    return { tooltipContext, showTooltip, hideTooltip }
}
