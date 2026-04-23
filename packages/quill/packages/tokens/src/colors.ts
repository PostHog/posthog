/**
 * PostHog Design System — Color Tokens (hue-based theming)
 *
 * Surface/neutral colors are derived from a shared theme hue + tint.
 * Consumers can override `--theme-hue`, `--primary-light`,
 * `--primary-dark` (and optionally `--theme-dark-hue`, `--theme-tint`)
 * on `:root` to shift the palette at runtime — no rebuild required.
 *
 * Status colors (destructive, success, warning, info) are independent
 * of the theme hue.
 */

import { cssVarsFlat } from './css'
import { generateShadowCSS } from './shadow'
import { generateSpacingCSS } from './spacing'
import { generateFontSizeCSS, generateFontFamilyCSS } from './typography'

// ── Theme configuration ───────────────────────────────

export interface ThemeConfig {
    /** OKLCH hue angle (0–360) for light mode surfaces */
    hue: number
    /** OKLCH hue angle for dark mode surfaces */
    darkHue: number
    /** Base OKLCH chroma for neutral surface tinting (0 = pure grey) */
    tint: number
    /**
     * Full brand color for light mode — any valid CSS color expression.
     * Consumers typically pass `oklch(L C H)` so L, C, and H are all
     * tunable per mode (not just hue). Override at runtime by setting
     * `--primary-light` on `:root` or any subtree.
     */
    primaryLight: string
    /** Full brand color for dark mode. See `primaryLight`. */
    primaryDark: string
}

/** PostHog default — warm yellowish-grey surfaces + orange/amber brand */
export const DEFAULT_THEME: ThemeConfig = {
    hue: 90,
    darkHue: 264,
    tint: 0.006,
    primaryLight: 'oklch(0.65 0.21 37.41)',
    primaryDark: 'oklch(0.83 0.16 84.71)',
}

// ── Types ─────────────────────────────────────────────

export type SemanticColorKey = string
export type ColorTuple = readonly [light: string, dark: string, tailwindClass: string]

// ── Color recipe helpers ──────────────────────────────

/**
 * Build an oklch() value referencing CSS custom properties so the
 * theme hue/tint can be overridden at runtime.
 *
 * When chromaScale is 1, emits `var(--theme-tint)` directly.
 * Otherwise wraps in `calc(var(--theme-tint) * scale)`.
 */
function surface(lightness: number, chromaScale: number, mode: 'light' | 'dark', alpha?: number): string {
    const hueVar = mode === 'light' ? 'var(--theme-hue)' : 'var(--theme-dark-hue)'
    const chromaExpr =
        chromaScale === 1
            ? 'var(--theme-tint)'
            : chromaScale === 0
              ? '0'
              : `calc(var(--theme-tint) * ${chromaScale})`
    const alphaSuffix = alpha !== undefined ? ` / ${alpha * 100}%` : ''
    return `oklch(${lightness} ${chromaExpr} ${hueVar}${alphaSuffix})`
}

/** Static oklch value (not theme-derived). `alpha` is a fraction in [0, 1]. */
function oklch(l: number, c: number, h: number, alpha?: number): string {
    return alpha !== undefined ? `oklch(${l} ${c} ${h} / ${alpha * 100}%)` : `oklch(${l} ${c} ${h})`
}

// ── Semantic color definitions ────────────────────────

/**
 * Build the full semantic color map.
 *
 * Surface/neutral colors use CSS custom property expressions so they
 * respond to runtime `--theme-hue` / `--theme-tint` overrides.
 * Status and brand colors are static OKLCH values.
 */
export function buildSemanticColors(): Record<string, ColorTuple> {
    return {
        // ── Surfaces (theme-derived) ──────────────────
        background: [surface(0.97, 1, 'light'), surface(0.145, 1.5, 'dark'), 'bg-background'],
        foreground: [oklch(0.13, 0.028, 262), oklch(0.967, 0.003, 265), 'text-foreground'],

        card: [surface(0.995, 0.3, 'light'), surface(0.2, 1.2, 'dark'), 'bg-card'],
        'card-foreground': [oklch(0.13, 0.028, 262), oklch(0.967, 0.003, 265), 'text-card-foreground'],

        popover: [surface(0.995, 0.3, 'light'), surface(0.21, 1.2, 'dark'), 'bg-popover'],
        'popover-foreground': [oklch(0.13, 0.028, 262), oklch(0.967, 0.003, 265), 'text-popover-foreground'],

        muted: [surface(0.94, 1.5, 'light'), surface(0.27, 1.5, 'dark'), 'bg-muted'],
        'muted-foreground': [oklch(0.446, 0.03, 257), oklch(0.709, 0, 0), 'text-muted-foreground'],

        accent: [surface(0.87, 0.8, 'light'), surface(0.35, 1.2, 'dark'), 'bg-accent'],
        'accent-foreground': [oklch(0.13, 0.028, 262), oklch(0.967, 0.003, 265), 'text-accent-foreground'],

        // ── Brand (driven by --primary-light / --primary-dark) ─
        primary: ['var(--primary-light)', 'var(--primary-dark)', 'bg-primary'],
        'primary-foreground': [oklch(1, 0, 0), oklch(0.13, 0.028, 262), 'text-primary-foreground'],

        secondary: [oklch(0.31, 0, 0), oklch(0.86, 0, 0), 'bg-secondary'],
        'secondary-foreground': [oklch(1, 0, 0), oklch(0.13, 0.028, 262), 'text-secondary-foreground'],

        // ── Status (independent of theme hue) ─────────
        destructive: [oklch(0.92, 0.03, 32.22), oklch(0.24, 0.03, 2.79), 'bg-destructive'],
        'destructive-foreground': [
            oklch(0.59, 0.2, 23.61),
            oklch(0.6316, 0.1927, 24.53),
            'text-destructive-foreground',
        ],

        success: [oklch(0.94, 0.06, 154.03), oklch(0.27, 0.04, 157.6), 'bg-success'],
        'success-foreground': [
            oklch(0.448, 0.119, 151.328),
            oklch(0.925, 0.084, 155.995),
            'text-success-foreground',
        ],

        warning: [oklch(0.93, 0.04, 74.41), oklch(0.29, 0.03, 75), 'bg-warning'],
        'warning-foreground': [oklch(0.476, 0.114, 61.907), oklch(0.77, 0.14, 99.29), 'text-warning-foreground'],

        info: [oklch(0.882, 0.059, 254.128), oklch(0.4242, 0.1982, 265.5, 0.4), 'bg-info'],
        'info-foreground': [oklch(0.49, 0.02, 254), oklch(0.882, 0.059, 254.128), 'text-info-foreground'],

        // ── Borders & rings (theme-derived) ───────────
        border: [surface(0.90, 0.8, 'light'), surface(0.27, 1.2, 'dark'), 'border-border'],
        input: [surface(0.81, 0.5, 'light'), surface(0.30, 1.5, 'dark'), 'border-input'],
        ring: [oklch(0.446, 0.03, 257), oklch(0.709, 0, 0), 'border-ring'],

        // ── Interactive fills for default button/ interactive elements ───────────
        // Darkest fill in light mode, lightest in dark mode
        'fill-expanded': [
            'oklch(0.87 0 0 / 60%)',
            'oklch(0.55 0 0 / 35%)',
            'bg-fill-expanded',
        ],
        // Medium fill 
        'fill-selected': [
            'oklch(0.87 0 0 / 40%)',
            'oklch(0.55 0 0 / 25%)',
            'bg-fill-selected',
        ],
        // Lightest fill in light mode, darkest in dark mode
        'fill-hover': [
            'oklch(0.87 0 0 / 20%)',
            'oklch(0.55 0 0 / 15%)',
            'bg-fill-hover',
        ],
    } as const
}

export const semanticColors = buildSemanticColors()

// ── Style generation config ───────────────────────────

export interface StylesConfig {
    /** Include @layer base reset rules (apps only) */
    includeBaseLayer?: boolean
    /**
     * CSS selector to scope all token CSS vars to. When set, vars are only
     * defined inside elements matching this selector, preventing clashes
     * with the consumer's existing CSS custom properties.
     *
     * Example: `'[data-quill]'` — consumer adds `data-quill` to wrapper
     * elements. During migration the attribute moves up the DOM tree;
     * when it reaches `<html>` the scope is effectively global and can
     * be removed.
     */
    scope?: string
    /**
     * CSS selector(s) for dark mode. Accepts a single selector or an
     * array — when multiple are given they are combined with `:is()`
     * so any of them activates dark mode.
     *
     * Default: `['.dark', '[theme="dark"]']` (both `.dark` class and
     * `theme="dark"` attribute work out of the box).
     */
    darkSelector?: string | string[]
}

// ── Helpers ───────────────────────────────────────────

/** Flat object for one theme */
export function resolveTheme(mode: 'light' | 'dark'): Record<string, string> {
    const i = mode === 'light' ? 0 : 1
    return Object.fromEntries(Object.entries(semanticColors).map(([k, v]) => [k, v[i]])) as Record<string, string>
}

/**
 * Names of tokens that are theme-derived and must be emitted on `*` (not
 * `:root`) so local `[--theme-hue:X]` overrides re-evaluate per-element.
 *
 * Direct references to `--theme-hue`, `--theme-dark-hue`, `--theme-tint`,
 * or `--primary-light` / `--primary-dark` are validated at module load
 * (see `assertThemeDerivedSyncedWithColors` below). The `fill-*` tokens are transitive — they reference
 * `var(--accent)` / `var(--muted)` rather than a theme var directly, so
 * they can't be auto-detected and must be listed explicitly.
 */
const THEME_DERIVED_TOKENS: ReadonlySet<string> = new Set([
    'background',
    'card',
    'popover',
    'muted',
    'accent',
    'primary',
    'border',
    'input',
    // Transitive: reference var(--accent) / var(--muted) — must also live
    // on `*` to re-evaluate on local overrides.
    'fill-hover',
    'fill-expanded',
    'fill-selected',
])

/**
 * Build-time guard: every token whose value contains a direct reference
 * to one of the theme variables MUST appear in `THEME_DERIVED_TOKENS`.
 * Otherwise it would land on `:root` and local subtree overrides
 * (`[--theme-hue:X]`) would silently fail for it.
 *
 * This runs once at module load. It only catches direct references;
 * transitive references (e.g. `fill-*` → `var(--accent)`) must be kept
 * in the set manually.
 */
function assertThemeDerivedSyncedWithColors(colors: Record<string, ColorTuple>): void {
    const DIRECT_THEME_VARS = [
        'var(--theme-hue)',
        'var(--theme-dark-hue)',
        'var(--theme-tint)',
        'var(--primary-light)',
        'var(--primary-dark)',
    ]
    for (const [key, [light, dark]] of Object.entries(colors)) {
        const refsThemeVar = DIRECT_THEME_VARS.some((v) => light.includes(v) || dark.includes(v))
        if (refsThemeVar && !THEME_DERIVED_TOKENS.has(key)) {
            throw new Error(
                `[@posthog/quill-tokens] Token "${key}" references a theme variable ` +
                    `but is missing from THEME_DERIVED_TOKENS. Add it to the set in colors.ts ` +
                    `or local [--theme-hue:X] overrides will silently fail for this token.`
            )
        }
    }
}

assertThemeDerivedSyncedWithColors(semanticColors)

/** Normalize darkSelector option into a single CSS selector string. */
function resolveDarkSelector(raw?: string | string[]): string {
    const defaults = ['.dark', '[theme="dark"]']
    const selectors = raw === undefined ? defaults : typeof raw === 'string' ? [raw] : raw
    return selectors.length === 1 ? selectors[0] : `:is(${selectors.join(', ')})`
}

/** Generate color-system.css (:root light + .dark overrides) */
export function generateColorSystemCSS(
    theme: ThemeConfig = DEFAULT_THEME,
    opts: Pick<StylesConfig, 'scope' | 'darkSelector'> = {}
): string {
    const { scope } = opts
    const darkSelector = resolveDarkSelector(opts.darkSelector)

    const themeKnobs = (indent = '  '): string =>
        [
            `${indent}--radius: 0.625rem;`,
            `${indent}--theme-hue: ${theme.hue};`,
            `${indent}--theme-dark-hue: ${theme.darkHue};`,
            `${indent}--theme-tint: ${theme.tint};`,
            `${indent}--primary-light: ${theme.primaryLight};`,
            `${indent}--primary-dark: ${theme.primaryDark};`,
        ].join('\n')

    // Split colors into static (safe on :root) vs theme-derived (need * for local overrides)
    const partition = (i: number): { staticVars: Record<string, string>; dynamicVars: Record<string, string> } => {
        const staticVars: Record<string, string> = {}
        const dynamicVars: Record<string, string> = {}
        for (const [k, v] of Object.entries(semanticColors)) {
            if (THEME_DERIVED_TOKENS.has(k)) {
                dynamicVars[k] = v[i]
            } else {
                staticVars[k] = v[i]
            }
        }
        return { staticVars, dynamicVars }
    }

    const light = partition(0)
    const dark = partition(1)

    // ── Scoped mode ─────────────────────────────────────
    // All vars gated behind the scope selector to avoid clashing
    // with the consumer's existing CSS custom properties.
    if (scope) {
        const scopeSel = `:is(${scope}, ${scope} *)`
        // Handle both ancestor-dark (`.dark [data-quill]`) and same-element
        // dark (`[data-quill].dark`) so dark mode works regardless of where
        // the dark selector lives relative to the scope element.
        const darkScopeSel = `:is(${darkSelector} ${scope}, ${scope}${darkSelector}, ${darkSelector} ${scope} *, ${scope}${darkSelector} *)`

        return `/* Auto-generated by @posthog/quill-tokens — do not edit manually */

/*
 * Scoped output — all token vars are gated behind \`${scope}\` so they
 * do not clash with the consumer's existing CSS custom properties.
 * Add the \`${scope.replace(/[[\]]/g, '')}\` attribute to wrapper elements
 * where quill components are rendered.
 *
 * Dark mode: works when the dark selector is on an ancestor of the scope
 * element (.dark > [data-quill]) OR on the scope element itself
 * ([data-quill].dark).
 */
${scope} {
  color-scheme: light;
}

:is(${darkSelector} ${scope}, ${scope}${darkSelector}) {
  color-scheme: dark;
}

${scopeSel} {
${themeKnobs()}
${cssVarsFlat(light.staticVars)}
${cssVarsFlat(light.dynamicVars)}

  /* Override Tailwind --color-* theme tokens within scope so utilities
   * like bg-accent, text-foreground, border-border resolve to quill's
   * values instead of the consumer's global theme. */
${generateColorMappingsCSS()}
}

${darkScopeSel} {
${cssVarsFlat(dark.staticVars)}
${cssVarsFlat(dark.dynamicVars)}
}
`
    }

    // ── Unscoped mode (default) ─────────────────────────
    return `/* Auto-generated by @posthog/quill-tokens — do not edit manually */

:root {
  color-scheme: light;
}

${darkSelector} {
  color-scheme: dark;
}

/* Theme knobs — override these to shift the palette */
:root {
${themeKnobs()}
}

/* Static colors (no theme-var references, safe on :root) */
:root {
${cssVarsFlat(light.staticVars)}
}

${darkSelector} {
${cssVarsFlat(dark.staticVars)}
}

/*
 * Theme-derived colors — set on * so each element resolves
 * var(--theme-hue) / var(--primary-light) from its own scope.
 * This enables local overrides like [--theme-hue:200] on a container.
 */
* {
${cssVarsFlat(light.dynamicVars)}
}

:is(${darkSelector}, ${darkSelector} *) {
${cssVarsFlat(dark.dynamicVars)}
}
`
}

/** Generate Tailwind v4 @theme color mappings (--color-* → var(--*)) */
function generateColorMappingsCSS(): string {
    return Object.keys(semanticColors)
        .map((k) => `  --color-${k}: var(--${k});`)
        .join('\n')
}

/**
 * Generate Tailwind v4 @theme + @custom-variant + optional @layer base.
 *
 * Does NOT include `@import "tailwindcss"` or `@import "color-system.css"` —
 * those are the consuming app's responsibility (they must resolve from the
 * app's node_modules, not from tokens/dist/).
 *
 * Two modes:
 *  - **Library** (includeBaseLayer: false): Just the @theme inline block
 *    so Tailwind can generate utility classes. Used by packages.
 *
 *  - **App** (includeBaseLayer: true): @theme + base layer resets.
 *    Used by apps/web, apps/storybook.
 */
export function generateStylesCSS(config: StylesConfig = {}): string {
    const { includeBaseLayer = false, scope } = config
    const darkSelector = resolveDarkSelector(config.darkSelector)

    const darkVariantBody = `&:is(${darkSelector}, ${darkSelector} *)`
    const lines: string[] = [
        '/* Auto-generated by @posthog/quill-tokens — do not edit manually */',
        '',
        `@custom-variant dark (${darkVariantBody});`,
    ]
    lines.push('')

    // ── @theme inline ──────────────────────────────────
    lines.push('@theme inline {')
    lines.push('  --animate-skeleton: skeleton 2s -1s infinite linear;')
    lines.push('  --animate-pulse-glow: pulse-glow 2s -1s infinite linear;')
    lines.push('  --animate-horizontal-shake: horizontal-shake 0.3s ease-out;')
    lines.push('  --animate-radar: radar 2s ease-out infinite;')
    lines.push('')
    lines.push('  /* --- Colors --- */')
    lines.push(generateColorMappingsCSS())
    lines.push('')
    lines.push('  /* --- Spacing --- */')
    lines.push(generateSpacingCSS())
    lines.push('')
    lines.push('  /* --- Font sizes --- */')
    lines.push(generateFontSizeCSS())
    lines.push('')
    lines.push('  /* --- Font families --- */')
    lines.push(generateFontFamilyCSS())
    lines.push('')
    lines.push('  /* --- Shadows --- */')
    lines.push(generateShadowCSS())
    lines.push('')
    lines.push('  /* --- Radius (derived from --radius base) --- */')
    lines.push('  --radius-sm: calc(var(--radius) - 4px);')
    lines.push('  --radius-md: calc(var(--radius) - 2px);')
    lines.push('  --radius-lg: var(--radius);')
    lines.push('  --radius-xl: calc(var(--radius) + 4px);')
    lines.push('  --radius-2xl: calc(var(--radius) + 8px);')
    lines.push('  --radius-3xl: calc(var(--radius) + 12px);')
    lines.push('  --radius-4xl: calc(var(--radius) + 16px);')
    lines.push('')
    lines.push('  @keyframes skeleton {')
    lines.push('    to {')
    lines.push('      background-position: -200% 0;')
    lines.push('    }')
    lines.push('  }')
    lines.push('')
    lines.push('  @keyframes pulse-glow {')
    lines.push('    0%, 100% { box-shadow: 0 0 2px 1px var(--pulse-glow-color, var(--color-accent)) }')
    lines.push('    50% { box-shadow: 0 0 6px 2px var(--pulse-glow-color, var(--color-accent)) }')
    lines.push('  }')
    lines.push('')
    lines.push('  @keyframes horizontal-shake {')
    lines.push('    0% { transform: translateX(0); }')
    lines.push('    25% { transform: translateX(5px); }')
    lines.push('    50% { transform: translateX(-5px); }')
    lines.push('    75% { transform: translateX(2px); }')
    lines.push('    100% { transform: translateX(0); }')
    lines.push('  }')
    lines.push('')
    lines.push('  @keyframes radar {')
    lines.push('    0% { transform: scale(1); opacity: 0.5; }')
    lines.push('    100% { transform: scale(1.5); opacity: 0; }')
    lines.push('  }')
    lines.push('}')

    if (includeBaseLayer) {
        lines.push('')
        lines.push('@layer base {')
        if (scope) {
            lines.push(`  ${scope}, ${scope} * {`)
            lines.push('    @apply border-border outline-ring/50;')
            lines.push('  }')
        } else {
            lines.push('  * {')
            lines.push('    @apply border-border outline-ring/50;')
            lines.push('  }')
            lines.push('  body {')
            lines.push('    @apply bg-background text-foreground;')
            lines.push('  }')
        }
        lines.push('}')
    }

    lines.push('')
    return lines.join('\n')
}
