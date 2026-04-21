/**
 * PostHog Design System — Border Radius Tokens
 *
 * Note: Tailwind v4 uses --radius as a base value in color-system.css (0.625rem).
 * These are the static design-token values for direct use.
 * The @theme block in styles.css derives --radius-* from the base --radius var.
 */

export const borderRadius = {
    none: '0px',
    sm: '4px',
    md: '6px',
    lg: '8px',
    xl: '12px',
    full: '9999px',
} as const

export type BorderRadius = typeof borderRadius
