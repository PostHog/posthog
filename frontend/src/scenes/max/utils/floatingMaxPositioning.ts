import { useLayoutEffect, useRef, useState } from 'react'
import { useValues } from 'kea'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

/**
 * Positioning utilities and drag behavior for Max AI floating components
 */

// Constants
const PANEL_FIXED_DISTANCE = 4 // pixels from panel edge

// Types
export interface Position {
    x: number
    y: number
}

export interface PositionWithSide extends Position {
    side: 'left' | 'right'
}

export interface PanelDimensions {
    sidePanelWidth: number
    projectPanelWidth: number
    xPadding: number
}

/**
 * Gets the computed CSS variable value from an element
 * @param variable - CSS variable name (e.g., '--scene-padding')
 * @param className - Optional class name to get the variable from specific element
 * @returns The parsed numeric value of the CSS variable
 */
export function getCSSVariableValue(variable: string, className?: string): number {
    let element: Element | null = null

    if (className) {
        const elements = document.getElementsByClassName(className)
        if (elements.length === 0) {
            return 0
        }
        element = elements[0]
    } else {
        element = document.documentElement
    }

    if (!element) {
        return 0
    }

    const value = getComputedStyle(element).getPropertyValue(variable).trim()

    if (value.endsWith('rem')) {
        const remValue = parseFloat(value)
        const rootFontSize = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
        return remValue * rootFontSize
    }

    return parseFloat(value) || 0
}

// Positioning Utilities
// ===================

/**
 * Get the dimensions of layout panels
 */
export function getPanelDimensions(): PanelDimensions {
    const sidePanel = document.getElementById('side-panel')
    const sidePanelWidth = sidePanel?.getBoundingClientRect().width || 0

    const projectPanel = document.getElementById('project-panel-layout')
    const projectPanelWidth = projectPanel?.getBoundingClientRect().width || 0

    const xPadding = getCSSVariableValue('--scene-padding', 'Navigation3000')

    return {
        sidePanelWidth,
        projectPanelWidth,
        xPadding,
    }
}

/**
 * Calculate the CSS positioning for floating elements based on side preference
 */
export function calculateCSSPosition(side: 'left' | 'right'): React.CSSProperties {
    const { sidePanelWidth, projectPanelWidth, xPadding } = getPanelDimensions()

    if (side === 'left') {
        return {
            left: `${projectPanelWidth + xPadding + PANEL_FIXED_DISTANCE}px`,
        }
    }

    return {
        right: `${sidePanelWidth + xPadding + PANEL_FIXED_DISTANCE}px`,
    }
}

/**
 * Get the dimensions of the floating max avatar element
 */
export function getFloatingMaxDimensions(): { width: number; height: number } {
    const floatingMax = document.getElementById('floating-max')
    const rect = floatingMax?.getBoundingClientRect()

    return {
        width: rect?.width || 0,
        height: rect?.height || 0,
    }
}

/**
 * Get the dimensions of a specific element
 */
export function getElementDimensions(element: HTMLElement | null): { width: number; height: number } {
    const rect = element?.getBoundingClientRect()

    return {
        width: rect?.width || 0,
        height: rect?.height || 0,
    }
}

/**
 * Calculate the absolute snap position for draggable elements
 */
export function calculateSnapPosition(
    mouseX: number,
    bottomOffset: number,
    elementWidth: number = 0,
    dragStartX?: number,
    currentSide?: 'left' | 'right',
    snapThreshold?: number,
    elementHeight?: number
): PositionWithSide {
    const windowWidth = window.innerWidth
    const windowHeight = window.innerHeight

    let isRightSide = mouseX > windowWidth / 2

    // If we have drag start position and current side, check if we should snap to opposite side
    if (dragStartX !== undefined && currentSide !== undefined && snapThreshold !== undefined) {
        const dragDistanceX = mouseX - dragStartX
        const shouldSnapToOpposite = Math.abs(dragDistanceX) > snapThreshold

        if (shouldSnapToOpposite) {
            // Snap to opposite side if drag distance exceeds threshold
            isRightSide = currentSide === 'left' ? true : false
        } else {
            // Stay on current side if drag distance is below threshold
            isRightSide = currentSide === 'right'
        }
    }

    const { sidePanelWidth, projectPanelWidth, xPadding } = getPanelDimensions()

    const finalX = isRightSide
        ? windowWidth - (sidePanelWidth + xPadding + PANEL_FIXED_DISTANCE + elementWidth)
        : projectPanelWidth + xPadding + PANEL_FIXED_DISTANCE

    const finalY = windowHeight - (elementHeight || elementWidth) - bottomOffset

    return {
        x: finalX,
        y: finalY,
        side: isRightSide ? 'right' : 'left',
    }
}

export function useFloatingMaxPosition(): {
    floatingMaxPositionStyle: React.CSSProperties
    shouldAnimate: boolean
} {
    const { isFloatingMaxExpanded, floatingMaxPosition, floatingMaxDragState } = useValues(maxGlobalLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)
    const [shouldAnimate, setShouldAnimate] = useState(false)
    const prevExpandedRef = useRef(isFloatingMaxExpanded)
    const [floatingMaxPositionStyle, setFloatingMaxPositionStyle] = useState<React.CSSProperties>({})

    // Only animate when transitioning from collapsed to expanded
    useLayoutEffect(() => {
        const wasCollapsed = !prevExpandedRef.current
        const isNowExpanded = isFloatingMaxExpanded

        if (wasCollapsed && isNowExpanded) {
            setShouldAnimate(true)
            // Clear animation flag after animation completes
            const timer = setTimeout(() => setShouldAnimate(false), 200)
            return () => clearTimeout(timer)
        }

        prevExpandedRef.current = isFloatingMaxExpanded
    }, [isFloatingMaxExpanded])

    // Update position style when layout changes
    useLayoutEffect(() => {
        const side = floatingMaxPosition?.side || 'right'
        const baseStyle = isFloatingMaxExpanded
            ? {
                  borderRadius: '8px',
                  transformOrigin: floatingMaxPosition?.side === 'left' ? 'bottom left' : 'bottom right',
                  ...(shouldAnimate
                      ? { animation: 'MaxFloatingInput__ExpandFromAvatar 0.2s cubic-bezier(0.4, 0, 0.2, 1)' }
                      : {}),
              }
            : {
                  borderRadius: '50%',
              }

        setFloatingMaxPositionStyle({
            ...calculateCSSPosition(side),
            ...baseStyle,
        })
        // oxlint-disable-next-line exhaustive-deps
    }, [
        isFloatingMaxExpanded,
        isLayoutNavCollapsed,
        floatingMaxDragState,
        floatingMaxPosition,
        shouldAnimate,
        sidePanelOpen,
    ])

    return {
        floatingMaxPositionStyle,
        shouldAnimate,
    }
}
