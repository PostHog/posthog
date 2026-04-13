#!/usr/bin/env node
/**
 * Generates CSS files from design tokens.
 *
 * Output:
 *   dist/color-system.css  — :root + .dark CSS custom properties
 *   dist/tailwind.css       — @theme + @custom-variant + @layer base (for apps)
 *   dist/tailwind-lib.css   — @theme + @custom-variant only (for library packages)
 *
 * Note: Neither tailwind.css nor tailwind-lib.css include `@import "tailwindcss"`.
 * The consuming app/package must import tailwindcss itself.
 */

import { writeFileSync, mkdirSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { generateColorSystemCSS, generateStylesCSS } from './colors.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const distDir = resolve(__dirname, '..', 'dist')

mkdirSync(distDir, { recursive: true })

// 1. Color system (CSS custom properties for light/dark)
writeFileSync(resolve(distDir, 'color-system.css'), generateColorSystemCSS())

// 2. App stylesheet (@theme + base layer, no @import "tailwindcss")
writeFileSync(resolve(distDir, 'tailwind.css'), generateStylesCSS({ includeBaseLayer: true }))

// 3. Library stylesheet (@theme only, no base layer)
writeFileSync(resolve(distDir, 'tailwind-lib.css'), generateStylesCSS({ includeBaseLayer: false }))
