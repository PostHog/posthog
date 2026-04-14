#!/usr/bin/env node
/**
 * Pre-compiles the Tailwind entry point at src/index.css into a flat
 * stylesheet at dist/quill.css. Consumers import the compiled output via
 * `@posthog/quill/styles.css` and need zero Tailwind setup of their own.
 *
 * Also copies the `@theme inline` block from `@posthog/quill-tokens` to
 * `dist/theme.css` and re-exposes it as `@posthog/quill/theme.css`. This
 * is the *opt-in* path for consumers who want their own Tailwind to
 * generate utility classes against quill's design tokens (e.g.
 * `text-muted-foreground`) — see README §"Authoring
 * against quill tokens".
 *
 * Runs `@tailwindcss/cli` as a child process so we don't have to pin
 * against its programmatic API (which is unstable across minor versions).
 */

import { spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(__dirname, '..')

const input = resolve(packageRoot, 'src/index.css')
const output = resolve(packageRoot, 'dist/quill.css')

mkdirSync(dirname(output), { recursive: true })

// @tailwindcss/cli exposes its binary as `tailwindcss`
const result = spawnSync('pnpm', ['exec', 'tailwindcss', '--input', input, '--output', output, '--minify'], {
    cwd: packageRoot,
    stdio: 'inherit',
})

if (result.status !== 0) {
    process.exit(result.status ?? 1)
}

// Copy the raw `@theme inline` block from quill-tokens into dist/theme.css.
// This file is intentionally NOT precompiled — consumers run it through
// their own Tailwind v4 instance so the `@theme` declarations register
// quill's design tokens with their compiler. Without this, consumer code
// like `bg-fill-hover` is silently dropped because the consumer's
// Tailwind has no idea `--color-fill-hover` exists.
const themeSource = resolve(packageRoot, 'node_modules/@posthog/quill-tokens/dist/tailwind-lib.css')
const themeOutput = resolve(packageRoot, 'dist/theme.css')

if (!existsSync(themeSource)) {
    throw new Error(
        `Cannot build @posthog/quill/theme.css: ${themeSource} does not exist. ` +
            `Make sure @posthog/quill-tokens has built first (run pnpm --filter ` +
            `'@posthog/quill...' build from the monorepo root to build workspace ` +
            `dependencies in topological order).`,
    )
}

copyFileSync(themeSource, themeOutput)
