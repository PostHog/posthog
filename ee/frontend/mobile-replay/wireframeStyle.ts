import { MobileStyles, wireframe } from './mobile.types'

function ensureUnit(value: string | number): string {
    return typeof value === 'number' ? `${value}px` : value.replace(/px$/g, '') + 'px'
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
        svgBorderStyles.rx = ensureUnit(style.borderRadius)
    }

    return svgBorderStyles
}

export function makePositionStyles(wireframe: wireframe): string {
    let styles = ''
    if (wireframe.width) {
        styles += `width: ${ensureUnit(wireframe.width)};`
    }
    if (wireframe.height) {
        styles += `height: ${ensureUnit(wireframe.height)};`
    }
    if (wireframe.x || wireframe.y) {
        styles += `position: absolute;`
        if (wireframe.x) {
            styles += `left: ${ensureUnit(wireframe.x)};`
        }
        if (wireframe.y) {
            styles += `top: ${ensureUnit(wireframe.y)};`
        }
    }
    return styles
}

function makeLayoutStyles(wireframe: wireframe): string {
    let styles = ''
    if (wireframe.style?.verticalAlign) {
        styles += `align-items: ${
            { top: 'flex-start', center: 'center', bottom: 'flex-end' }[wireframe.style.verticalAlign]
        };`
    }
    if (wireframe.style?.horizontalAlign) {
        styles += `justify-content: ${
            { left: 'flex-start', center: 'center', right: 'flex-end' }[wireframe.style.horizontalAlign]
        };`
    }
    if (styles.length) {
        styles += `display: flex;`
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
    styles += makeLayoutStyles(wireframe)
    return styles
}
