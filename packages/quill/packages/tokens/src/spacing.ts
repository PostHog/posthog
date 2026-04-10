/**
 * PostHog Design System — Spacing Tokens
 */

import { cssVars } from './css'

export const spacing = {
    0: '0px',
    1: '4px',
    2: '8px',
    3: '12px',
    4: '16px',
    5: '20px',
    6: '24px',
    8: '32px',
    10: '40px',
    12: '48px',
    16: '64px',
} as const

export type Spacing = typeof spacing

/** Generate Tailwind v4 @theme spacing vars */
export function generateSpacingCSS(): string {
    return cssVars(spacing as unknown as Record<string, string>, 'spacing')
}
