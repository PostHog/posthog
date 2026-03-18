import { hexToRGB, hexToRGBA } from 'lib/utils'

import { ProductTourAppearance } from '~/types'

import { DEFAULT_APPEARANCE } from '../constants'

function getFontFamily(fontFamily?: string): string {
    if (fontFamily === 'inherit') {
        return 'inherit'
    }

    const defaultFontStack =
        'BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"'
    return fontFamily ? `${fontFamily}, ${defaultFontStack}` : `-apple-system, ${defaultFontStack}`
}

const NAME_TO_HEX: Record<string, string> = {
    black: '#000000',
    white: '#ffffff',
    red: '#ff0000',
    green: '#008000',
    blue: '#0000ff',
    gray: '#808080',
    grey: '#808080',
}

const BLACK_TEXT_COLOR = '#020617'

function getContrastingTextColor(color: string = '#ffffff'): string {
    let r: number, g: number, b: number

    if (color.startsWith('#')) {
        const rgb = hexToRGB(color)
        r = rgb.r
        g = rgb.g
        b = rgb.b
    } else if (color.startsWith('rgb')) {
        const match = color.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/)
        if (match) {
            r = parseInt(match[1])
            g = parseInt(match[2])
            b = parseInt(match[3])
        } else {
            return BLACK_TEXT_COLOR
        }
    } else {
        const hex = NAME_TO_HEX[color.toLowerCase()]
        if (hex) {
            const rgb = hexToRGB(hex)
            r = rgb.r
            g = rgb.g
            b = rgb.b
        } else {
            return BLACK_TEXT_COLOR
        }
    }

    // HSP (Highly Sensitive Poo) equation from http://alienryderflex.com/hsp.html
    const hsp = Math.sqrt(0.299 * (r * r) + 0.587 * (g * g) + 0.114 * (b * b))
    return hsp > 127.5 ? BLACK_TEXT_COLOR : 'white'
}

export function addProductTourCSSVariablesToElement(element: HTMLElement, appearance?: ProductTourAppearance): void {
    const merged = { ...DEFAULT_APPEARANCE, ...appearance }
    const style = element.style

    style.setProperty('--ph-tour-background-color', merged.backgroundColor ?? '#ffffff')
    style.setProperty('--ph-tour-text-color', merged.textColor ?? '#1d1f27')
    style.setProperty('--ph-tour-button-color', merged.buttonColor ?? '#1d1f27')
    style.setProperty('--ph-tour-border-radius', `${merged.borderRadius ?? 8}px`)
    style.setProperty('--ph-tour-button-border-radius', `${merged.buttonBorderRadius ?? 6}px`)
    style.setProperty('--ph-tour-border-color', merged.borderColor ?? '#e5e7eb')
    style.setProperty('--ph-tour-font-family', getFontFamily(merged.fontFamily))

    style.setProperty('--ph-tour-text-secondary-color', hexToRGBA(merged.textColor ?? '#1d1f27', 0.6))
    style.setProperty('--ph-tour-branding-text-color', getContrastingTextColor(merged.backgroundColor))
    style.setProperty('--ph-tour-button-text-color', getContrastingTextColor(merged.buttonColor))
    style.setProperty('--ph-tour-box-shadow', merged.boxShadow ?? '0 4px 12px rgba(0, 0, 0, 0.15)')
    style.setProperty('--ph-tour-overlay-color', merged.showOverlay ? 'rgba(0, 0, 0, 0.5)' : 'transparent')
    style.setProperty('--ph-tour-z-index', String(merged.zIndex ?? 2147483647))

    style.setProperty('--ph-tour-button-secondary-color', 'transparent')
    style.setProperty('--ph-tour-button-secondary-text-color', merged.textColor ?? '#1d1f27')
    style.setProperty('--ph-tour-max-width', '320px')
    style.setProperty('--ph-tour-padding', '16px')
}
