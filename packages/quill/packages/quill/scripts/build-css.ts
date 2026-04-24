#!/usr/bin/env node
/**
 * Emits three CSS artifacts for consumers — NO pre-compiled utility
 * stylesheet. Consumer's Tailwind v4 instance scans the compiled
 * primitive/component/block JS and generates exactly the utilities it
 * reaches. This eliminates the cascade-layer fight that a pre-compiled
 * `dist/quill.css` created when consumer and quill both shipped a
 * `utilities` layer.
 *
 *   dist/tokens.css   @theme + light/dark CSS custom properties. Consumer
 *                     imports this to register quill's design tokens with
 *                     their Tailwind v4 and unlock `bg-fill-hover`,
 *                     `text-muted-foreground`, etc.
 *
 *   dist/base.css     One `* { border-border outline-ring/50 }` reset.
 *                     Load-bearing — without it primitives that write
 *                     plain `border` fall back to currentColor.
 *
 *   dist/tailwind.css A single `@source "./**\/*.js"` directive. When
 *                     consumer `@import`s this file, Tailwind resolves
 *                     paths relative to this file's location inside
 *                     node_modules/@posthog/quill/dist, so it scans our
 *                     compiled library JS for class-name strings and
 *                     compiles them into the consumer's output — no
 *                     brittle `../node_modules/...` paths required.
 */

import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(__dirname, '..')
const distDir = resolve(packageRoot, 'dist')

mkdirSync(distDir, { recursive: true })

const tokensSource = resolve(packageRoot, 'node_modules/@posthog/quill-tokens/dist/tailwind-lib.css')
const colorsSource = resolve(packageRoot, 'node_modules/@posthog/quill-tokens/dist/color-system.css')
const tokensScopedSource = resolve(packageRoot, 'node_modules/@posthog/quill-tokens/dist/tailwind-lib.scoped.css')
const colorsScopedSource = resolve(packageRoot, 'node_modules/@posthog/quill-tokens/dist/color-system.scoped.css')
/*
 * Primitive BEM CSS. Primitives build with `cssCodeSplit: false` so every
 * `.quill-*` rule across every primitive lands in this single file. It MUST
 * be shipped with the umbrella — without it consumers see the BEM class
 * names but no styling.
 */
const primitivesSource = resolve(
    packageRoot,
    'node_modules/@posthog/quill-primitives/dist/quill-primitives.css'
)

for (const path of [tokensSource, colorsSource, tokensScopedSource, colorsScopedSource, primitivesSource]) {
    if (!existsSync(path)) {
        throw new Error(
            `Cannot build quill CSS: ${path} missing. Run @posthog/quill-tokens and ` +
                `@posthog/quill-primitives builds first ` +
                `(\`pnpm --filter '@posthog/quill...' build\`).`
        )
    }
}

const theme = readFileSync(tokensSource, 'utf8')
const colors = readFileSync(colorsSource, 'utf8')
const themeScoped = readFileSync(tokensScopedSource, 'utf8')
const colorsScoped = readFileSync(colorsScopedSource, 'utf8')

/*
 * Tailwind v4 default theme keys that quill primitives depend on but
 * that get silently dropped when a consumer uses `@config legacy.js`
 * (v3 compat mode). Shipping them here makes quill self-sufficient
 * regardless of whether the consumer runs pure v4 or the v3 legacy
 * bridge, so classes like `text-xs/relaxed`, `tracking-tight`, etc.
 * always resolve against known values.
 *
 * Inserted into the SAME `@theme inline { ... }` block as quill-tokens
 * by splicing before its closing brace.
 */
const quillTailwindDefaults = `
  /* --- Line heights (leading modifier syntax: \`text-xs/relaxed\`) --- */
  --leading-none: 1;
  --leading-tight: 1.25;
  --leading-snug: 1.375;
  --leading-normal: 1.5;
  --leading-relaxed: 1.625;
  --leading-loose: 2;

  /* --- Tracking (letter-spacing) --- */
  --tracking-tighter: -0.05em;
  --tracking-tight: -0.025em;
  --tracking-normal: 0em;
  --tracking-wide: 0.025em;
  --tracking-wider: 0.05em;
  --tracking-widest: 0.1em;

  /* --- Font weights --- */
  --font-weight-thin: 100;
  --font-weight-extralight: 200;
  --font-weight-light: 300;
  --font-weight-normal: 400;
  --font-weight-medium: 500;
  --font-weight-semibold: 600;
  --font-weight-bold: 700;
  --font-weight-extrabold: 800;
  --font-weight-black: 900;
`

const themeWithDefaults = theme.replace(/}\s*$/, `${quillTailwindDefaults}}\n`)
if (themeWithDefaults === theme) {
    throw new Error(
        'build-css: failed to inject Tailwind defaults into tailwind-lib.css — ' +
            'expected the file to end with a closing brace. Check the output of ' +
            '`@posthog/quill-tokens build` and update the regex if the format changed.'
    )
}

writeFileSync(
    resolve(distDir, 'tokens.css'),
    [
        '/* @posthog/quill — design tokens.',
        ' * Import from your Tailwind entry after `@import "tailwindcss"`.',
        ' * Provides:',
        ' *   1. light / dark CSS custom property values (:root + .dark)',
        ' *   2. the @theme inline block that registers those values as',
        ' *      Tailwind v4 theme keys so `bg-fill-hover`, `rounded-md`,',
        ' *      `text-xxs` etc. compile in the consumer\'s own Tailwind.',
        ' */',
        '',
        colors,
        '',
        themeWithDefaults,
    ].join('\n')
)

writeFileSync(
    resolve(distDir, 'base.css'),
    [
        '/* @posthog/quill — base reset.',
        ' *',
        ' * Load-bearing single rule: primitives author plain `border` (no',
        ' * colour modifier) expecting the current border colour to resolve',
        ' * to `--color-border`. Without this reset Tailwind v4 falls back',
        ' * to `currentColor` and every bordered primitive looks broken.',
        ' *',
        ' * Deliberately does NOT paint `body { bg-background text-foreground }`',
        ' * — consumer owns their page chrome.',
        ' */',
        '@layer base {',
        '    * {',
        '        @apply border-border outline-ring/50;',
        '    }',
        '}',
        '',
    ].join('\n')
)

writeFileSync(
    resolve(distDir, 'tailwind.css'),
    [
        '/* @posthog/quill — Tailwind source directive.',
        ' *',
        ' * Consumer imports this file from their Tailwind v4 entry. The',
        ' * glob path is relative to THIS file\'s on-disk location (inside',
        ' * node_modules/@posthog/quill/dist after install), so it works',
        ' * under pnpm, hoisted, and Docker layouts without needing',
        ' * consumer-side `../node_modules/@posthog/quill/...` paths.',
        ' *',
        ' * Tailwind scans the compiled library JS for literal class',
        ' * strings (cva variants, `cn(...)` calls, template-less className',
        ' * props) and generates the matching utilities in the consumer\'s',
        ' * own `utilities` layer — no pre-compiled stylesheet, no',
        ' * cascade-layer fight with consumer Tailwind output.',
        ' */',
        '@source "./**/*.js";',
        '',
    ].join('\n')
)

// Ship the raw light/dark CSS custom property file alongside too, for
// consumers that only want colour values without the @theme registration.
copyFileSync(colorsSource, resolve(distDir, 'color-system.css'))

// Ship the primitive BEM CSS alongside tokens/base — consumers import
// `@posthog/quill/primitives.css` to register the `.quill-*` component rules.
copyFileSync(primitivesSource, resolve(distDir, 'primitives.css'))

// ── Scoped variants ──────────────────────────────────────
// Gated behind [data-quill] with [theme="dark"] dark mode for
// consumers migrating from an existing design system.

const themeScopedWithDefaults = themeScoped.replace(/}\s*$/, `${quillTailwindDefaults}}\n`)
if (themeScopedWithDefaults === themeScoped) {
    throw new Error(
        'build-css: failed to inject Tailwind defaults into tailwind-lib.scoped.css — ' +
            'expected the file to end with a closing brace.'
    )
}

writeFileSync(
    resolve(distDir, 'tokens.scoped.css'),
    [
        '/* @posthog/quill — scoped design tokens.',
        ' * All CSS vars are gated behind [data-quill] so they do not clash',
        ' * with existing consumer CSS custom properties.',
        ' * Dark mode uses [theme="dark"] instead of .dark.',
        ' */',
        '',
        colorsScoped,
        '',
        themeScopedWithDefaults,
    ].join('\n')
)

writeFileSync(
    resolve(distDir, 'base.scoped.css'),
    [
        '/* @posthog/quill — scoped base reset.',
        ' * Same as base.css but only applies inside [data-quill] boundaries.',
        ' */',
        '@layer base {',
        '    [data-quill], [data-quill] * {',
        '        @apply border-border outline-ring/50;',
        '    }',
        '}',
        '',
    ].join('\n')
)

copyFileSync(colorsScopedSource, resolve(distDir, 'color-system.scoped.css'))

console.info(
    'wrote dist/tokens.css, dist/base.css, dist/tailwind.css, dist/color-system.css, ' +
        'dist/tokens.scoped.css, dist/base.scoped.css, dist/color-system.scoped.css'
)
