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

// PNG, because each SVG is several times larger.
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
    fs.writeFileSync(path.join(OUT_DIR, 'console.css'), inlineFonts(result.css))
}

// The admin CSP allows fonts only from data: URIs and Google Fonts, so the RoundHog faces go into the
// stylesheet itself.
function inlineFonts(css) {
    return css.replace(/url\(['"]?fonts\/([\w-]+\.woff2)['"]?\)/g, (_match, file) => {
        const font = fs.readFileSync(path.join(BRAND_DIST, 'fonts/subsets', file)).toString('base64')
        return `url(data:font/woff2;base64,${font})`
    })
}

function writeMonoIcon() {
    const icon = fs.readFileSync(path.join(FRONTEND, 'public/posthog-icon.svg'), 'utf8')
    fs.writeFileSync(path.join(OUT_DIR, 'posthog-icon-mono.svg'), icon.replace(/fill="[^"]+"/g, 'fill="#fff"'))
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

const CONSOLE_SOURCE_ROOTS = ['posthog', 'ee', 'products']
const SKIPPED_DIRECTORIES = new Set(['node_modules', '__pycache__', 'migrations'])

// A console contribution lives in a console.py, or in a module of a console package such as posthog/admin/console/.
function isConsoleSource(file) {
    return (
        file.endsWith('.py') &&
        (path.basename(file) === 'console.py' || path.basename(path.dirname(file)) === 'console')
    )
}

function findConsoleSources(directory) {
    const files = []
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const entryPath = path.join(directory, entry.name)
        if (entry.isDirectory() && !entry.name.startsWith('.') && !SKIPPED_DIRECTORIES.has(entry.name)) {
            files.push(...findConsoleSources(entryPath))
        } else if (entry.isFile() && isConsoleSource(entryPath)) {
            files.push(entryPath)
        }
    }
    return files
}

function consoleSourceFiles() {
    return CONSOLE_SOURCE_ROOTS.flatMap((root) => findConsoleSources(path.join(REPO_ROOT, root)))
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
fs.rmSync(path.join(OUT_DIR, 'fonts'), { recursive: true, force: true })
await buildStylesheet()
writeMonoIcon()
copyHoggies()
await writeCrests()
