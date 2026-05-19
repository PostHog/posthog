/**
 * PostHog Design System — Shadow Tokens
 */

import { cssVars } from './css'

export const shadow = {
    sm: '0 2px 0 color-mix(in oklab, var(--border), transparent 10%)',
    md: '0 3px 0 color-mix(in oklab, var(--border), transparent 10%)',
    lg: '0 6px 0 color-mix(in oklab, var(--border), transparent 10%)',
    line: '0 -1px 0px 0px color-mix(in oklab, var(--border), transparent 10%)'
} as const

export type Shadow = typeof shadow

/** Generate Tailwind v4 @theme shadow vars (--shadow-*) */
export function generateShadowCSS(): string {
    return cssVars(shadow as unknown as Record<string, string>, 'shadow')
}
