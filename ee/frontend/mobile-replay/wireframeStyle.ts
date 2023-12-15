import { MobileStyles, wireframe, wireframeProgress } from './mobile.types'

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

function makeBorderStyles(wireframe: wireframe, styleOverride?: MobileStyles): string {
    let styles = ''

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (!combinedStyles) {
        return styles
    }

    if (isUnitLike(combinedStyles.borderWidth)) {
        const borderWidth = ensureUnit(combinedStyles.borderWidth)
        styles += `border-width: ${borderWidth};`
    }
    if (isUnitLike(combinedStyles.borderRadius)) {
        const borderRadius = ensureUnit(combinedStyles.borderRadius)
        styles += `border-radius: ${borderRadius};`
    }
    if (combinedStyles?.borderColor) {
        styles += `border-color: ${combinedStyles.borderColor};`
    }

    if (styles.length > 0) {
        styles += `border-style: solid;`
    }

    return styles
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

function makeLayoutStyles(wireframe: wireframe, styleOverride?: MobileStyles): string {
    let styles = ''

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (combinedStyles.verticalAlign) {
        styles += `align-items: ${
            { top: 'flex-start', center: 'center', bottom: 'flex-end' }[combinedStyles.verticalAlign]
        };`
    }
    if (combinedStyles.horizontalAlign) {
        styles += `justify-content: ${
            { left: 'flex-start', center: 'center', right: 'flex-end' }[combinedStyles.horizontalAlign]
        };`
    }
    if (styles.length) {
        styles += `display: flex;`
    }
    return styles
}

function makeFontStyles(wireframe: wireframe, styleOverride?: MobileStyles): string {
    let styles = ''

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (!combinedStyles) {
        return styles
    }

    if (isUnitLike(combinedStyles.fontSize)) {
        styles += `font-size: ${ensureUnit(combinedStyles?.fontSize)};`
    }
    if (combinedStyles.fontFamily) {
        styles += `font-family: ${combinedStyles.fontFamily};`
    }
    return styles
}

export function makeIndeterminateProgressStyles(wireframe: wireframeProgress, styleOverride?: MobileStyles): string {
    let styles = ''
    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }
    if (combinedStyles.backgroundColor) {
        styles += `background-color: ${combinedStyles.backgroundColor};`
    }
    styles += makePositionStyles(wireframe)
    styles += `border: 4px solid ${combinedStyles.borderColor || combinedStyles.color || 'transparent'};`
    styles += `border-radius: 50%;border-top: 4px solid #fff;`
    styles += `animation: spin 2s linear infinite;`

    return styles
}

export function makeDeterminateProgressStyles(wireframe: wireframeProgress, styleOverride?: MobileStyles): string {
    let styles = ''
    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (combinedStyles.backgroundColor) {
        styles += `background-color: ${combinedStyles.backgroundColor};`
    }
    styles += makePositionStyles(wireframe)
    styles += 'border-radius: 50%;'
    const radialGradient = `radial-gradient(closest-side, white 80%, transparent 0 99.9%, white 0)`
    const conicGradient = `conic-gradient(${combinedStyles.color || 'black'} calc(${wireframe.value} * 1%), ${
        combinedStyles.backgroundColor
    } 0)`
    styles += `background: ${radialGradient}, ${conicGradient};`

    return styles
}

/**
 * normally use makeStylesString instead, but sometimes you need styles without any colors applied
 * */
export function makeMinimalStyles(wireframe: wireframe, styleOverride?: MobileStyles): string {
    let styles = ''

    styles += makePositionStyles(wireframe)
    styles += makeLayoutStyles(wireframe, styleOverride)
    styles += makeFontStyles(wireframe, styleOverride)

    return styles
}

export function makeStylesString(wireframe: wireframe, styleOverride?: MobileStyles): string {
    let styles = ''

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (combinedStyles.color) {
        styles += `color: ${combinedStyles.color};`
    }
    if (combinedStyles.backgroundColor) {
        styles += `background-color: ${combinedStyles.backgroundColor};`
    }

    styles += makeBorderStyles(wireframe, styleOverride)
    styles += makeMinimalStyles(wireframe, styleOverride)

    return styles
}

export function makeHTMLStyles(): string {
    return 'height: 100vh; width: 100vw;'
}

export function makeBodyStyles(): string {
    return 'height: 100vh; width: 100vw;'
}
