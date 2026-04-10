/**
 * PostHog Design System — Typography Tokens
 */

import { fontFamilyValue } from './css'

const ROOT_FONT_SIZE = 14

function rem(px: number): string {
    return `${px / ROOT_FONT_SIZE}rem`
}

export const fontSize = {
    xxs: [rem(10), { lineHeight: rem(12) }], // 0.7143rem (10px)
    xs: [rem(12), { lineHeight: rem(16) }], // 0.8571rem (12px)
    sm: [rem(14), { lineHeight: rem(14) }], // 1rem (14px)
    base: [rem(16), { lineHeight: rem(24) }], // 1.1429rem (16px)
    lg: [rem(18), { lineHeight: rem(28) }], // 1.2857rem (18px)
    xl: [rem(20), { lineHeight: rem(28) }], // 1.4286rem (20px)
    '2xl': [rem(24), { lineHeight: rem(32) }], // 1.7143rem (24px)
} as const

export const fontFamily = {
    sans: ['-apple-system', 'BlinkMacSystemFont', 'Inter', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'sans-serif'],
    mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
} as const

export type FontSize = typeof fontSize
export type FontFamily = typeof fontFamily

/** Generate Tailwind v4 @theme font-size vars (--text-* + --text-*--line-height) */
export function generateFontSizeCSS(): string {
    return Object.entries(fontSize)
        .map(([k, [size, { lineHeight }]]) => `  --text-${k}: ${size};\n  --text-${k}--line-height: ${lineHeight};`)
        .join('\n')
}

/** Generate Tailwind v4 @theme font-family vars (--font-*) */
export function generateFontFamilyCSS(): string {
    return Object.entries(fontFamily)
        .map(([k, fonts]) => `  --font-${k}: ${fontFamilyValue(fonts)};`)
        .join('\n')
}
