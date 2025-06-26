import { useEffect, useRef, useState } from 'react'

export function useTooltipHover(): {
    showTooltip: (variantKey: string) => void
    hideTooltip: () => void
    showTooltipFromTooltip: (variantKey: string) => void
    isTooltipVisible: (variantKey: string) => boolean
} {
    const [hoveredVariant, setHoveredVariant] = useState<string | null>(null)
    const [hoveredTooltip, setHoveredTooltip] = useState<string | null>(null)
    const hideTimeoutRef = useRef<NodeJS.Timeout | null>(null)

    const showTooltip = (variantKey: string): void => {
        if (hideTimeoutRef.current) {
            clearTimeout(hideTimeoutRef.current)
            hideTimeoutRef.current = null
        }
        setHoveredVariant(variantKey)
        setHoveredTooltip(null)
    }

    const hideTooltip = (): void => {
        hideTimeoutRef.current = setTimeout(() => {
            setHoveredVariant(null)
            setHoveredTooltip(null)
        }, 150)
    }

    const showTooltipFromTooltip = (variantKey: string): void => {
        if (hideTimeoutRef.current) {
            clearTimeout(hideTimeoutRef.current)
            hideTimeoutRef.current = null
        }
        setHoveredTooltip(variantKey)
        setHoveredVariant(null)
    }

    const isTooltipVisible = (variantKey: string): boolean => {
        return hoveredVariant === variantKey || hoveredTooltip === variantKey
    }

    // Cleanup timeout on unmount to prevent memory leaks
    useEffect(() => {
        return () => {
            if (hideTimeoutRef.current) {
                clearTimeout(hideTimeoutRef.current)
            }
        }
    }, [])

    return {
        showTooltip,
        hideTooltip,
        showTooltipFromTooltip,
        isTooltipVisible,
    }
}
