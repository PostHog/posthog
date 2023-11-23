import { MobileStyles, wireframe } from './mobile.types'

function ensureUnit(value: string | number): string {
    return typeof value === 'number' ? `${value}px` : value
}

function makeBorderStyles(wireframe: wireframe): string {
    let styles = ''

    if (wireframe.style?.borderWidth) {
        const borderWidth = ensureUnit(wireframe.style.borderWidth)
        styles += `border-width: ${borderWidth};`
    }
    if (wireframe.style?.borderRadius) {
        const borderRadius = ensureUnit(wireframe.style.borderRadius)
        styles += `border-radius: ${borderRadius};`
    }
    if (wireframe.style?.borderColor) {
        styles += `border-color: ${wireframe.style.borderColor};`
    }

    if (styles.length > 0) {
        styles += `border-style: solid;`
    }

    return styles
}

export function makeSvgBorder(style: MobileStyles | undefined): Record<string, string> {
    const svgBorderStyles: Record<string, string> = {}

    if (style?.borderWidth) {
        svgBorderStyles['stroke-width'] = style.borderWidth.toString()
    }
    if (style?.borderColor) {
        svgBorderStyles.stroke = style.borderColor
    }
    if (style?.borderRadius) {
        svgBorderStyles.rx = style.borderRadius.toString()
    }

    return svgBorderStyles
}

export function makePositionStyles(wireframe: wireframe): string {
    let styles = ''
    if (wireframe.width) {
        styles += `width: ${wireframe.width}px;`
    }
    if (wireframe.height) {
        styles += `height: ${wireframe.height}px;`
    }
    if (wireframe.x || wireframe.y) {
        styles += `position: absolute;`
        if (wireframe.x) {
            styles += `left: ${wireframe.x}px;`
        }
        if (wireframe.y) {
            styles += `top: ${wireframe.y}px;`
        }
    }
    return styles
}

export function makeStylesString(wireframe: wireframe): string {
    let styles = ''
    if (wireframe.style?.color) {
        styles += `color: ${wireframe.style.color};`
    }
    if (wireframe.style?.backgroundColor) {
        styles += `background-color: ${wireframe.style.backgroundColor};`
    }
    styles += makeBorderStyles(wireframe)
    styles += makePositionStyles(wireframe)
    return styles
}
