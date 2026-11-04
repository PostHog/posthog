// Build frontend/public/admin-console/: the staff console's quill stylesheet and its @posthog/brand assets.

import tailwindcss from '@tailwindcss/postcss'
import autoprefixer from 'autoprefixer'
import fs from 'fs'
import { createRequire } from 'module'
import path from 'path'
import postcss from 'postcss'
import postcssPresetEnv from 'postcss-preset-env'
import { fileURLToPath, pathToFileURL } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(__dirname, '..')
const SOURCE = path.join(FRONTEND, 'src/styles/admin-console.css')
const OUT_DIR = path.join(FRONTEND, 'public/admin-console')

const FONT_FACES = ['RoundHog-latin', 'RoundHog-Medium-latin', 'RoundHog-SemiBold-latin', 'RoundHog-Bold-latin']

// Hoggies show up at moments, not in working areas. The PNG is a fraction of the SVG's size.
const HOGGIES = ['traffic-police', 'asleep', 'stamp-approved', 'desk-wizard']

const require = createRequire(import.meta.url)
const BRAND_DIST = path.join(path.dirname(require.resolve('@posthog/brand/package.json')), 'dist')

// Browserslist otherwise follows NODE_ENV, and a shell with NODE_ENV=development would build for the
// development targets, which keep oklch() colors that older production browsers cannot read.
process.env.BROWSERSLIST_ENV = 'production'

async function buildStylesheet() {
    const result = await postcss([tailwindcss, autoprefixer, postcssPresetEnv({ stage: 0 })]).process(
        fs.readFileSync(SOURCE, 'utf8'),
        { from: SOURCE }
    )
    for (const warning of result.warnings()) {
        console.warn(warning.toString())
    }
    fs.writeFileSync(path.join(OUT_DIR, 'console.css'), result.css)
}

function copyFonts() {
    const fontDir = path.join(OUT_DIR, 'fonts')
    fs.mkdirSync(fontDir, { recursive: true })
    for (const face of FONT_FACES) {
        fs.copyFileSync(path.join(BRAND_DIST, 'fonts/subsets', `${face}.woff2`), path.join(fontDir, `${face}.woff2`))
    }
}

function copyHoggies() {
    const hoggieDir = path.join(OUT_DIR, 'hoggies')
    fs.mkdirSync(hoggieDir, { recursive: true })
    for (const slug of HOGGIES) {
        fs.copyFileSync(
            path.join(BRAND_DIST, 'generated/hoggies/png', `${slug}.png`),
            path.join(hoggieDir, `${slug}.png`)
        )
    }
}

// Ship only the crests a panel owner names in the console Python code, not all sixty.
const REPO_ROOT = path.resolve(FRONTEND, '..')
const CREST_ARGUMENT = /crest="([a-z0-9-]+)"/g

function consoleSourceFiles() {
    const files = fs
        .readdirSync(path.join(REPO_ROOT, 'posthog/admin/console'))
        .filter((name) => name.endsWith('.py'))
        .map((name) => path.join(REPO_ROOT, 'posthog/admin/console', name))
    for (const product of fs.readdirSync(path.join(REPO_ROOT, 'products'))) {
        const consoleModule = path.join(REPO_ROOT, 'products', product, 'backend/console.py')
        if (fs.existsSync(consoleModule)) {
            files.push(consoleModule)
        }
    }
    return files
}

async function writeCrests() {
    const crestDir = path.join(OUT_DIR, 'crests')
    fs.rmSync(crestDir, { recursive: true, force: true })
    fs.mkdirSync(crestDir, { recursive: true })
    const slugs = new Set()
    for (const file of consoleSourceFiles()) {
        for (const match of fs.readFileSync(file, 'utf8').matchAll(CREST_ARGUMENT)) {
            slugs.add(match[1])
        }
    }
    const svgDir = path.join(BRAND_DIST, 'generated/crests/mini/svg')
    for (const slug of [...slugs].sort()) {
        const { svg } = await import(pathToFileURL(path.join(svgDir, `${slug}.mjs`)).href)
        fs.writeFileSync(path.join(crestDir, `${slug}.svg`), svg)
    }
}

fs.mkdirSync(OUT_DIR, { recursive: true })
await buildStylesheet()
copyFonts()
copyHoggies()
await writeCrests()
