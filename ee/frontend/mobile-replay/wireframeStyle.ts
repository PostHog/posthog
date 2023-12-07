import { MobileStyles, wireframe } from './mobile.types'

function isNumber(candidate: unknown): candidate is number {
    return typeof candidate === 'number'
}

function isString(candidate: unknown): candidate is string {
    return typeof candidate === 'string'
}

function isUnitLike(candidate: unknown): candidate is string | number {
    return isNumber(candidate) || (isString(candidate) && candidate.length > 0)
}

function ensureUnit(value: string | number): string {
    return isNumber(value) ? `${value}px` : value.replace(/px$/g, '') + 'px'
}

function makeBorderStyles(wireframe: wireframe): string {
    let styles = ''

    if (!wireframe.style) {
        return styles
    }

    if (isUnitLike(wireframe.style.borderWidth)) {
        const borderWidth = ensureUnit(wireframe.style.borderWidth)
        styles += `border-width: ${borderWidth};`
    }
    if (isUnitLike(wireframe.style.borderRadius)) {
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

    if (!style) {
        return svgBorderStyles
    }

    if (isUnitLike(style.borderWidth)) {
        svgBorderStyles['stroke-width'] = ensureUnit(style.borderWidth)
    }
    if (style.borderColor) {
        svgBorderStyles.stroke = style.borderColor
    }
    if (isUnitLike(style.borderRadius)) {
        svgBorderStyles.rx = ensureUnit(style.borderRadius)
    }

    return svgBorderStyles
}

export function makePositionStyles(wireframe: wireframe): string {
    let styles = ''
    if (isNumber(wireframe.width)) {
        styles += `width: ${ensureUnit(wireframe.width)};`
    }
    if (isNumber(wireframe.height)) {
        styles += `height: ${ensureUnit(wireframe.height)};`
    }

    const posX = wireframe.x || 0
    const posY = wireframe.y || 0
    if (isNumber(posX) || isNumber(posY)) {
        styles += `position: fixed;`
        if (isNumber(posX)) {
            styles += `left: ${ensureUnit(posX)};`
        }
        if (isNumber(posY)) {
            styles += `top: ${ensureUnit(posY)};`
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

function makeFontStyles(wireframe: wireframe): string {
    let styles = ''

    if (!wireframe.style) {
        return styles
    }

    if (isUnitLike(wireframe.style.fontSize)) {
        styles += `font-size: ${ensureUnit(wireframe.style?.fontSize)};`
    }
    if (wireframe.style.fontFamily) {
        styles += `font-family: ${wireframe.style.fontFamily};`
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
    styles += makeFontStyles(wireframe)
    return styles
}

export function makeHTMLStyles(): string {
    return 'height: 100vh; width: 100vw;'
}

export function makeBodyStyles(): string {
    return 'height: 100vh; width: 100vw;'
}
