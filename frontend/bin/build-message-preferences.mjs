// Build frontend/public/message-preferences.css, the stylesheet the messaging preference pages load.
//
// This runs the same PostCSS plugins as the app's CSS build in common/esbuilder/utils.mjs, so the
// pages get the app's production browser targets, and every plugin comes from the workspace lockfile.
//
// Usage:
//   node bin/build-message-preferences.mjs

import tailwindcss from '@tailwindcss/postcss'
import autoprefixer from 'autoprefixer'
import fs from 'fs'
import path from 'path'
import postcss from 'postcss'
import postcssPresetEnv from 'postcss-preset-env'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(__dirname, '..')
const SOURCE = path.join(FRONTEND, 'src/styles/message-preferences.css')
const OUT_FILE = path.join(FRONTEND, 'public/message-preferences.css')

// Browserslist otherwise follows NODE_ENV, and a shell with NODE_ENV=development would build for the
// development targets, which keep oklch() colors that older production browsers cannot read.
process.env.BROWSERSLIST_ENV = 'production'

const result = await postcss([tailwindcss, autoprefixer, postcssPresetEnv({ stage: 0 })]).process(
    fs.readFileSync(SOURCE, 'utf8'),
    { from: SOURCE }
)
for (const warning of result.warnings()) {
    console.warn(warning.toString())
}
fs.writeFileSync(OUT_FILE, result.css)
