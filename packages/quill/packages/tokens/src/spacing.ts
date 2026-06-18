/**
 * PostHog Design System — Spacing
 *
 * Quill follows Tailwind v4's single-base spacing model: every spacing
 * utility (padding, margin, gap, inset, size) resolves to
 * `calc(var(--spacing) * N)`. A single `--spacing` custom property in the
 * `@theme` block gives consumers:
 *
 *   - **Accessibility** — spacing scales with root font-size preferences
 *     (users who bump browser text size get proportional padding/gaps)
 *   - **Continuous scale** — `p-7`, `p-[17]`, `p-1.5` all work without
 *     pre-defining discrete steps
 *   - **Parametric** — override `--spacing` on any element to shift the
 *     scale for that subtree (e.g. `[--spacing:0.3125rem]` on a density
 *     boundary)
 *   - **Consistency** — same unit (rem) as typography tokens
 *
 * Default base: `0.25rem` (= 4px at the conventional 16px root font-size),
 * matching Tailwind v4's own default so consumer muscle-memory translates.
 *
 * ## Overriding
 *
 * ```css
 * :root { --spacing: 0.3125rem; } // 5px base — a slightly looser scale
 * ```
 *
 * ## Using in TypeScript (CSS-in-JS, React Native, Figma)
 *
 * ```ts
 * import { spacing, spacingPx } from '@posthog/quill-tokens'
 * spacing(4)    // '1rem'  — for CSS-in-JS
 * spacingPx(4)  // 16      — for React Native / Figma plugins
 * ```
 */

/** Base spacing unit as a numeric rem value. Single source of truth. */
export const SPACING_BASE_REM = 0.25

/** Base spacing unit as a CSS length string. */
export const SPACING_BASE = `${SPACING_BASE_REM}rem`

/** Conventional root font-size in CSS pixels (only used by the px helper). */
const DEFAULT_ROOT_FONT_SIZE_PX = 16

/**
 * Compute a spacing value at a given scale step as a rem string.
 *
 * Equivalent to Tailwind's `p-{step}`, `gap-{step}`, `m-{step}`,
 * `size-{step}`. Fractional steps work.
 *
 * @example
 * spacing(0)    // '0rem'
 * spacing(4)    // '1rem'
 * spacing(1.5)  // '0.375rem'
 */
export function spacing(step: number): string {
    return `${SPACING_BASE_REM * step}rem`
}

/**
 * Compute a spacing value in CSS pixels, for non-browser consumers
 * (React Native, Figma plugins, PNG/SVG exporters, email templates).
 *
 * Assumes the conventional 16px root font-size. If your consumer uses a
 * different root size, scale the result by `root / 16`.
 *
 * @example
 * spacingPx(4)  // 16
 * spacingPx(6)  // 24
 */
export function spacingPx(step: number): number {
    return SPACING_BASE_REM * step * DEFAULT_ROOT_FONT_SIZE_PX
}

/**
 * Generate the Tailwind v4 `@theme` entry for the spacing base.
 *
 * Emits a single `--spacing` variable. Tailwind v4 generates the full
 * continuous utility scale from it via `calc(var(--spacing) * N)` — no
 * individual `--spacing-N` declarations needed.
 */
export function generateSpacingCSS(): string {
    return `  --spacing: ${SPACING_BASE};`
}
