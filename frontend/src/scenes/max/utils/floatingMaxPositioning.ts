/**
 * Comprehensive positioning utilities and drag behavior for Max AI floating components
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
 * Calculate the absolute snap position for draggable elements
 */
export function calculateSnapPosition(mouseX: number, bottomOffset: number, avatarWidth: number = 0): PositionWithSide {
    const windowWidth = window.innerWidth
    const windowHeight = window.innerHeight
    const isRightSide = mouseX > windowWidth / 2

    const { sidePanelWidth, projectPanelWidth, xPadding } = getPanelDimensions()

    const finalX = isRightSide
        ? windowWidth - (sidePanelWidth + xPadding + PANEL_FIXED_DISTANCE + avatarWidth)
        : projectPanelWidth + xPadding + PANEL_FIXED_DISTANCE

    const finalY = windowHeight - avatarWidth - bottomOffset

    return {
        x: finalX,
        y: finalY,
        side: isRightSide ? 'right' : 'left',
    }
}
