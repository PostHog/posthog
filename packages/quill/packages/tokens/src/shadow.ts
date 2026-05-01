/**
 * PostHog Design System — Shadow Tokens
 */

import { cssVars } from './css'

export const shadow = {
    sm: '0 1px 2px 0 rgba(0, 0, 0, 0.3)',
    md: '0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -2px rgba(0, 0, 0, 0.3)',
    lg: '0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -4px rgba(0, 0, 0, 0.3)',
} as const

export type Shadow = typeof shadow

/** Generate Tailwind v4 @theme shadow vars (--shadow-*) */
export function generateShadowCSS(): string {
    return cssVars(shadow as unknown as Record<string, string>, 'shadow')
}
