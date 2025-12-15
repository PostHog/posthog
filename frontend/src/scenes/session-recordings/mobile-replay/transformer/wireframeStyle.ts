import { wireframe, wireframeProgress } from '../mobile.types'
import { dataURIOrPNG } from './transformers'
import { StyleOverride } from './types'

function ensureTrailingSemicolon(styles: string): string {
    return styles.endsWith(';') ? styles : styles + ';'
}

function stripTrailingSemicolon(styles: string): string {
    return styles.endsWith(';') ? styles.slice(0, -1) : styles
}

export function asStyleString(styleParts: string[]): string {
    if (styleParts.length === 0) {
        return ''
    }
    return ensureTrailingSemicolon(
        styleParts
            .map(stripTrailingSemicolon)
            .filter((x) => !!x)
            .join(';')
    )
}

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
    const styleParts: string[] = []

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (isUnitLike(combinedStyles.borderWidth)) {
        const borderWidth = ensureUnit(combinedStyles.borderWidth)
        styleParts.push(`border-width: ${borderWidth}`)
    }
    if (isUnitLike(combinedStyles.borderRadius)) {
        const borderRadius = ensureUnit(combinedStyles.borderRadius)
        styleParts.push(`border-radius: ${borderRadius}`)
    }
    if (combinedStyles?.borderColor) {
        styleParts.push(`border-color: ${combinedStyles.borderColor}`)
    }

    if (styleParts.length > 0) {
        styleParts.push(`border-style: solid`)
    }

    return asStyleString(styleParts)
}

export function makeDimensionStyles(wireframe: wireframe): string {
    const styleParts: string[] = []

    if (wireframe.width === '100vw') {
        styleParts.push(`width: 100vw`)
    } else if (isNumber(wireframe.width)) {
        styleParts.push(`width: ${ensureUnit(wireframe.width)}`)
    }

    if (isNumber(wireframe.height)) {
        styleParts.push(`height: ${ensureUnit(wireframe.height)}`)
    }

    return asStyleString(styleParts)
}

export function makePositionStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    const styleParts: string[] = []

    styleParts.push(makeDimensionStyles(wireframe))

    if (styleOverride?.bottom) {
        styleParts.push(`bottom: 0`)
        styleParts.push(`position: fixed`)
    } else {
        const posX = wireframe.x || 0
        const posY = wireframe.y || 0
        if (isNumber(posX) || isNumber(posY)) {
            styleParts.push(`position: fixed`)
            if (isNumber(posX)) {
                styleParts.push(`left: ${ensureUnit(posX)}`)
            }
            if (isNumber(posY)) {
                styleParts.push(`top: ${ensureUnit(posY)}`)
            }
        }
    }

    if (styleOverride?.['z-index']) {
        styleParts.push(`z-index: ${styleOverride['z-index']}`)
    }

    return asStyleString(styleParts)
}

function makeLayoutStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    const styleParts: string[] = []

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (combinedStyles.verticalAlign) {
        styleParts.push(
            `align-items: ${{ top: 'flex-start', center: 'center', bottom: 'flex-end' }[combinedStyles.verticalAlign]}`
        )
    }
    if (combinedStyles.horizontalAlign) {
        styleParts.push(
            `justify-content: ${
                { left: 'flex-start', center: 'center', right: 'flex-end' }[combinedStyles.horizontalAlign]
            }`
        )
    }

    if (styleParts.length) {
        styleParts.push(`display: flex`)
    }

    if (isUnitLike(combinedStyles.paddingLeft)) {
        styleParts.push(`padding-left: ${ensureUnit(combinedStyles.paddingLeft)}`)
    }
    if (isUnitLike(combinedStyles.paddingRight)) {
        styleParts.push(`padding-right: ${ensureUnit(combinedStyles.paddingRight)}`)
    }
    if (isUnitLike(combinedStyles.paddingTop)) {
        styleParts.push(`padding-top: ${ensureUnit(combinedStyles.paddingTop)}`)
    }
    if (isUnitLike(combinedStyles.paddingBottom)) {
        styleParts.push(`padding-bottom: ${ensureUnit(combinedStyles.paddingBottom)}`)
    }

    return asStyleString(styleParts)
}

function makeFontStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    const styleParts: string[] = []

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (isUnitLike(combinedStyles.fontSize)) {
        styleParts.push(`font-size: ${ensureUnit(combinedStyles?.fontSize)}`)
    }

    if (combinedStyles.fontFamily) {
        styleParts.push(`font-family: ${combinedStyles.fontFamily}`)
    }

    return asStyleString(styleParts)
}

export function makeIndeterminateProgressStyles(wireframe: wireframeProgress, styleOverride?: StyleOverride): string {
    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    return asStyleString([
        makeBackgroundStyles(wireframe, styleOverride),
        makePositionStyles(wireframe),
        `border: 4px solid ${combinedStyles.borderColor || combinedStyles.color || 'transparent'};`,
        `border-radius: 50%;border-top: 4px solid #fff;`,
        `animation: spin 2s linear infinite;`,
    ])
}

export function makeDeterminateProgressStyles(wireframe: wireframeProgress, styleOverride?: StyleOverride): string {
    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    const radialGradient = `radial-gradient(closest-side, white 80%, transparent 0 99.9%, white 0)`
    const conicGradient = `conic-gradient(${combinedStyles.color || 'black'} calc(${wireframe.value} * 1%), ${
        combinedStyles.backgroundColor
    } 0)`

    return asStyleString([
        makeBackgroundStyles(wireframe, styleOverride),
        makePositionStyles(wireframe),
        'border-radius: 50%',

        `background: ${radialGradient}, ${conicGradient}`,
    ])
}

/**
 * normally use makeStylesString instead, but sometimes you need styles without any colors applied
 * */
export function makeMinimalStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    return asStyleString([
        makePositionStyles(wireframe, styleOverride),
        makeLayoutStyles(wireframe, styleOverride),
        makeFontStyles(wireframe, styleOverride),
    ])
}

export function makeBackgroundStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    let styleParts: string[] = []

    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    if (combinedStyles.backgroundColor) {
        styleParts.push(`background-color: ${combinedStyles.backgroundColor}`)
    }

    if (combinedStyles.backgroundImage) {
        const backgroundImageURL = combinedStyles.backgroundImage.startsWith('url(')
            ? combinedStyles.backgroundImage
            : `url('${dataURIOrPNG(combinedStyles.backgroundImage)}')`
        styleParts = styleParts.concat([
            `background-image: ${backgroundImageURL}`,
            `background-size: ${combinedStyles.backgroundSize || 'contain'}`,
            `background-repeat: ${combinedStyles.backgroundRepeat || 'no-repeat'}`,
        ])
    }

    return asStyleString(styleParts)
}

export function makeColorStyles(wireframe: wireframe, styleOverride?: StyleOverride): string {
    const combinedStyles = {
        ...wireframe.style,
        ...styleOverride,
    }

    const styleParts = [makeBackgroundStyles(wireframe, styleOverride), makeBorderStyles(wireframe, styleOverride)]
    if (combinedStyles.color) {
        styleParts.push(`color: ${combinedStyles.color}`)
    }

    return asStyleString(styleParts)
}

export function makeStylesString(wireframe: wireframe, styleOverride?: StyleOverride): string {
    return asStyleString([makeColorStyles(wireframe, styleOverride), makeMinimalStyles(wireframe, styleOverride)])
}

export function makeHTMLStyles(): string {
    return 'height: 100vh; width: 100vw;'
}

export function makeBodyStyles(): string {
    return 'height: 100vh; width: 100vw;'
}
