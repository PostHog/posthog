import { MobileStyles, wireframe, wireframeProgress } from './mobile.types'
import {dataURIOrPNG} from "./transformers";

// StyleOverride is defined here and not in the schema
// because these are overrides that the transformer is allowed to make
// not that clients are allowed to request
export type StyleOverride = MobileStyles & { bottom?: true }

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

function makeBorderStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
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

export function makeDimensionStyles(wireframe: wireframe): string {
    let styles = ''

    if (wireframe.width === '100vw') {
        styles += `width: 100vw;`
    } else if (isNumber(wireframe.width)) {
        styles += `width: ${ensureUnit(wireframe.width)};`
    }

    if (isNumber(wireframe.height)) {
        styles += `height: ${ensureUnit(wireframe.height)};`
    }

    return styles
}

export function makePositionStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    let styles = ''

    styles += makeDimensionStyles(wireframe)

    if (styleOverride?.bottom) {
        styles += `bottom: 0;`
        styles += `position: fixed;`
    } else {
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
    }

    return styles
}

function makeLayoutStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
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

function makeFontStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
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

export function makeIndeterminateProgressStyles(wireframe: wireframeProgress, styleOverride?: StyleOverride): string {
    let styles = ''
    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }
    styles += makeBackgroundStyles(wireframe, styleOverride)
    styles += makePositionStyles(wireframe)
    styles += `border: 4px solid ${combinedStyles.borderColor || combinedStyles.color || 'transparent'};`
    styles += `border-radius: 50%;border-top: 4px solid #fff;`
    styles += `animation: spin 2s linear infinite;`

    return styles
}

export function makeDeterminateProgressStyles(wireframe: wireframeProgress, styleOverride?: StyleOverride): string {
    let styles = ''
    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    styles += makeBackgroundStyles(wireframe, styleOverride)
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
export function makeMinimalStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    let styles = ''

    styles += makePositionStyles(wireframe, styleOverride)
    styles += makeLayoutStyles(wireframe, styleOverride)
    styles += makeFontStyles(wireframe, styleOverride)

    return styles
}

export function makeBackgroundStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    let styles = ''

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (combinedStyles.backgroundColor) {
        styles += `background-color: ${combinedStyles.backgroundColor};`
    }

    if (combinedStyles.backgroundImage) {
        const backgroundImageStyles = [
            `background-image: url(${dataURIOrPNG(combinedStyles.backgroundImage)})`,
            `background-size: ${combinedStyles.backgroundSize || 'auto'}`,
            'background-repeat: no-repeat'
        ]

        styles += backgroundImageStyles.join(';')
    }

    return styles
}

export function makeColorStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    let styles = ''

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (combinedStyles.color) {
        styles += `color: ${combinedStyles.color};`
    }
    styles += makeBackgroundStyles(wireframe, styleOverride)

    styles += makeBorderStyles(wireframe, styleOverride)

    return styles
}

function alwaysEndsWithSemicolon(styles: string): string {
    return styles.length > 0 && styles[styles.length - 1] !== ';' ? styles + ';' : styles
}

export function makeStylesString(wireframe: wireframe, styleOverride?: StyleOverride): string {
    let styles = ''

    styles += makeColorStyles(wireframe, styleOverride)
    styles += makeMinimalStyles(wireframe, styleOverride)

    return alwaysEndsWithSemicolon(styles)
}

export function makeHTMLStyles(): string {
    return 'height: 100vh; width: 100vw;'
}

export function makeBodyStyles(): string {
    return 'height: 100vh; width: 100vw;'
}
