/**
 * PostHog Design System — Typography Tokens
 */

import { fontFamilyValue } from './css'

const ROOT_FONT_SIZE = 16

function rem(px: number): string {
    return `${px / ROOT_FONT_SIZE}rem`
}

export const fontSize = {
    xxs: [rem(10), { lineHeight: rem(12) }],   // 0.625rem (10px), 0.75rem (12px)
    xs: [rem(12), { lineHeight: rem(16) }],    // 0.75rem (12px), 1rem (16px)
    sm: [rem(14), { lineHeight: rem(20) }],    // 0.875rem (14px), 1.25rem (20px)
    base: [rem(16), { lineHeight: rem(24) }],  // 1rem (16px), 1.5rem (24px)
    lg: [rem(18), { lineHeight: rem(28) }],    // 1.125rem (18px), 1.75rem (28px)
    xl: [rem(20), { lineHeight: rem(28) }],    // 1.25rem (20px), 1.75rem (28px)
    '2xl': [rem(24), { lineHeight: rem(32) }], // 1.5rem (24px), 2rem (32px)
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
