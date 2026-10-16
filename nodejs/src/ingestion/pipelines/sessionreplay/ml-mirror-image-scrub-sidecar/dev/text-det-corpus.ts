/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Synthetic web images with an exact ground-truth box for every word, for dev/text-det-bench.ts.
 *
 *   tsx dev/text-det-corpus.ts [--calibration]
 *
 * The labelled public sets cover scans, receipts and banners, but their boxes are hand-drawn and
 * their text sizes are whatever the set happened to contain. These images control both: every word's
 * box is its measured ink in the rendered image, and sizes, fonts, contrast and backgrounds are swept on
 * purpose, including the cases a detector finds hardest (small text, low contrast, light on dark, text
 * over texture).
 *
 * Seeded, so the same command always writes the same images.
 */
import { mkdir, writeFile } from 'node:fs/promises'
import sharp from 'sharp'

import { mulberry32 } from './bench-common.ts'
import { type GtImage, type GtWord } from './text-det-setup.ts'

// --calibration writes a disjoint seed range to its own set, for int8 calibration that never sees an eval image.
const CALIBRATION = process.argv.includes('--calibration')
const OUT = new URL(`../test-data/text-det/${CALIBRATION ? 'calibration' : 'synthetic'}/`, import.meta.url).pathname
const FIRST_SEED = CALIBRATION ? 100 : 0

const PHRASES = [
    'Dashboard',
    'Settings',
    'Log out',
    'Total revenue $48,201.55',
    'jane.doe@example.com',
    '+1 (415) 555-0132',
    'Card ending 4242',
    'Exp 08/27',
    'Order #A1B2C3',
    'Ship to 1200 Market St, San Francisco CA 94103',
    'Invoice 2026-0042',
    'Due 2026-07-15',
    'SSN 123-45-6789',
    'DOB 1990-04-12',
    'Acct 0098761234',
    'Search results for "quarterly forecast"',
    'Add to cart',
    'Free shipping on orders over $50',
    'Sale ends Sunday',
    '50% OFF',
    'Sign up for our newsletter',
    'Terms and conditions apply',
    'Maria Gonzalez',
    'Welcome back, Alex',
    'Your order has shipped',
    'Tracking 1Z999AA10123456784',
    'Password reset link sent',
    'Last login 2026-09-01 14:22',
    'Customer ID 88213',
    'Buy now',
    'Learn more',
    'New arrivals',
    'Q3 pipeline: 1,204 deals',
    'Conversion rate 3.4%',
    'Mon Tue Wed Thu Fri',
    'Unsubscribe',
    'Privacy policy',
    'ACME Corporation',
    '221B Baker Street, London NW1 6XE',
    'IBAN GB29 NWBK 6016 1331 9268 19',
]

const FONTS = ['Arial', 'Helvetica', 'Georgia', 'Times New Roman', 'Courier New', 'Verdana', 'Trebuchet MS', 'Impact']

interface Palette {
    background: string
    text: string[]
    buttonFills: string[]
}

const LIGHT: Palette = {
    background: '<rect width="100%" height="100%" fill="#ffffff"/>',
    text: ['#111827', '#374151', '#6b7280', '#9ca3af', '#2563eb', '#dc2626'],
    buttonFills: ['#2563eb', '#16a34a', '#111827', '#f59e0b'],
}
const GREY: Palette = { ...LIGHT, background: '<rect width="100%" height="100%" fill="#f3f4f6"/>' }
const DARK: Palette = {
    background: '<rect width="100%" height="100%" fill="#111827"/>',
    text: ['#f9fafb', '#d1d5db', '#9ca3af', '#6b7280', '#60a5fa'],
    buttonFills: ['#2563eb', '#dc2626', '#f9fafb'],
}

function texture(random: () => number): Palette {
    const frequency = (0.004 + random() * 0.02).toFixed(4)
    const seed = Math.floor(random() * 1000)
    const tint = ['#7c2d12', '#1e3a8a', '#14532d', '#581c87', '#0f172a'][Math.floor(random() * 5)]
    return {
        background:
            `<defs><filter id="t"><feTurbulence type="fractalNoise" baseFrequency="${frequency}" numOctaves="4" seed="${seed}"/></filter></defs>` +
            `<rect width="100%" height="100%" fill="${tint}"/>` +
            `<rect width="100%" height="100%" filter="url(#t)" opacity="0.75"/>`,
        text: ['#ffffff', '#fde047', '#111827'],
        buttonFills: ['#dc2626', '#111827', '#ffffff'],
    }
}

function gradient(random: () => number): Palette {
    const pairs = [
        ['#f97316', '#db2777'],
        ['#0ea5e9', '#6366f1'],
        ['#fef3c7', '#fde68a'],
        ['#e0f2fe', '#ffffff'],
    ]
    const [from, to] = pairs[Math.floor(random() * pairs.length)]
    const light = from.startsWith('#f') || from.startsWith('#e')
    return {
        background:
            `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${from}"/><stop offset="1" stop-color="${to}"/></linearGradient></defs>` +
            `<rect width="100%" height="100%" fill="url(#g)"/>`,
        text: light ? ['#111827', '#7c2d12', '#374151'] : ['#ffffff', '#111827', '#fef08a'],
        buttonFills: ['#111827', '#ffffff'],
    }
}

interface Layout {
    name: string
    width: number
    height: number
    devicePixelRatio: number
    cssFontPxRange: [number, number]
    palette: (random: () => number) => Palette
}

const LAYOUTS: Layout[] = [
    { name: 'desktop', width: 1920, height: 1080, devicePixelRatio: 1, cssFontPxRange: [9, 28], palette: () => LIGHT },
    {
        name: 'desktop-grey',
        width: 1440,
        height: 900,
        devicePixelRatio: 1,
        cssFontPxRange: [9, 24],
        palette: () => GREY,
    },
    { name: 'retina', width: 2880, height: 1800, devicePixelRatio: 2, cssFontPxRange: [9, 28], palette: () => LIGHT },
    { name: 'dark', width: 1280, height: 720, devicePixelRatio: 1, cssFontPxRange: [9, 32], palette: () => DARK },
    { name: 'mobile', width: 1170, height: 2532, devicePixelRatio: 3, cssFontPxRange: [10, 30], palette: () => LIGHT },
    {
        name: 'mobile-dark',
        width: 750,
        height: 1624,
        devicePixelRatio: 2,
        cssFontPxRange: [10, 30],
        palette: () => DARK,
    },
    { name: 'og-image', width: 1200, height: 628, devicePixelRatio: 1, cssFontPxRange: [14, 72], palette: gradient },
    { name: 'hero', width: 1600, height: 900, devicePixelRatio: 1, cssFontPxRange: [12, 96], palette: texture },
    { name: 'leaderboard', width: 728, height: 90, devicePixelRatio: 1, cssFontPxRange: [9, 32], palette: gradient },
    { name: 'mpu', width: 300, height: 250, devicePixelRatio: 1, cssFontPxRange: [8, 36], palette: texture },
    { name: 'product', width: 800, height: 800, devicePixelRatio: 1, cssFontPxRange: [9, 48], palette: () => LIGHT },
    { name: 'thumbnail', width: 480, height: 270, devicePixelRatio: 1, cssFontPxRange: [8, 40], palette: texture },
]

const SEEDS_PER_LAYOUT = 4

interface Run {
    x: number
    baseline: number
    fontPx: number
    font: string
    weight: 'normal' | 'bold'
    color: string
    text: string
    buttonFill?: string
}

const escapeXml = (s: string): string =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

type RunStyle = Omit<Run, 'x' | 'baseline' | 'buttonFill'>

/** Relative to the run's origin (x, baseline). */
interface Ink {
    left: number
    top: number
    width: number
    height: number
}

function textElement(run: RunStyle, x: number, baseline: number): string {
    return `<text x="${x}" y="${baseline}" font-family="${run.font}" font-size="${run.fontPx}" font-weight="${run.weight}" fill="${run.color}">${escapeXml(run.text)}</text>`
}

/** A canvas that holds the whole run, with the run's origin at (pad, baseline). */
function measurementCanvas(run: RunStyle): { pad: number; baseline: number; width: number; height: number } {
    const pad = Math.ceil(run.fontPx * 2)
    return {
        pad,
        baseline: pad + run.fontPx * 2,
        width: Math.ceil(run.text.length * run.fontPx * 1.1) + 2 * pad,
        height: Math.ceil(run.fontPx * 3) + 2 * pad,
    }
}

function svgOnCanvas(run: RunStyle, canvas: ReturnType<typeof measurementCanvas>): Buffer {
    return Buffer.from(
        `<svg xmlns="http://www.w3.org/2000/svg" width="${canvas.width}" height="${canvas.height}">${textElement(run, canvas.pad, canvas.baseline)}</svg>`
    )
}

async function measureInk(run: RunStyle): Promise<Ink> {
    const canvas = measurementCanvas(run)
    const { info } = await sharp(svgOnCanvas(run, canvas)).trim({ threshold: 1 }).toBuffer({ resolveWithObject: true })
    return {
        left: -(info.trimOffsetLeft ?? 0) - canvas.pad,
        top: -(info.trimOffsetTop ?? 0) - canvas.baseline,
        width: info.width,
        height: info.height,
    }
}

// Rasterizing a longer string changes a few alpha values of the glyphs already drawn by a few levels, while a glyph
// that moves by a fraction of a pixel changes its edge pixels by far more than this.
const ALPHA_NOISE = 16

// Word k's ink is what the prefix through word k adds to the prefix before it. Appending text never moves the glyphs
// already laid out, so these are the pixels word k has inside the whole run. Rendering a word alone, or hiding its
// neighbors in separate spans, loses the kerning at its edges and shifts it.
async function measureWordInks(run: RunStyle): Promise<{ text: string; ink: Ink }[]> {
    const canvas = measurementCanvas(run)
    const words = run.text.split(' ')
    const inks: { text: string; ink: Ink }[] = []
    let previousAlpha = new Uint8Array(canvas.width * canvas.height)
    for (const [k, word] of words.entries()) {
        const prefix = { ...run, text: words.slice(0, k + 1).join(' ') }
        const alpha = new Uint8Array(
            await sharp(svgOnCanvas(prefix, canvas)).ensureAlpha().extractChannel(3).raw().toBuffer()
        )
        let [left, top, right, bottom] = [canvas.width, canvas.height, -1, -1]
        for (let i = 0; i < alpha.length; i++) {
            const added = alpha[i] - previousAlpha[i]
            if (added < -ALPHA_NOISE) {
                throw new Error(`appending "${word}" to "${words.slice(0, k).join(' ')}" moved the prefix`)
            }
            if (added > ALPHA_NOISE) {
                const x = i % canvas.width
                const y = Math.floor(i / canvas.width)
                left = Math.min(left, x)
                top = Math.min(top, y)
                right = Math.max(right, x + 1)
                bottom = Math.max(bottom, y + 1)
            }
        }
        if (right < 0) {
            throw new Error(`"${word}" in "${run.text}" renders no ink`)
        }
        inks.push({
            text: word,
            ink: { left: left - canvas.pad, top: top - canvas.baseline, width: right - left, height: bottom - top },
        })
        previousAlpha = alpha
    }
    return inks
}

async function makeImage(layout: Layout, seed: number): Promise<{ png: Buffer; gt: GtImage }> {
    const random = mulberry32(seed * 7919 + layout.width)
    const palette = layout.palette(random)
    const margin = Math.round(Math.min(layout.width, layout.height) * 0.04)
    const logMin = Math.log(layout.cssFontPxRange[0] * layout.devicePixelRatio)
    const logMax = Math.log(layout.cssFontPxRange[1] * layout.devicePixelRatio)
    const runs: Run[] = []
    const runBoxes: [number, number, number, number][] = []
    const words: GtWord[] = []

    let top = margin
    while (top < layout.height - margin) {
        const fontPx = Math.round(Math.exp(logMin + random() * (logMax - logMin)))
        let x = margin + Math.floor(random() * fontPx * 3)
        const rowBottomLimit = layout.height - margin
        let rowHeight = 0
        let placed = 0
        for (let attempt = 0; attempt < 6 && x < layout.width - margin; attempt++) {
            const run = {
                fontPx,
                font: FONTS[Math.floor(random() * FONTS.length)],
                weight: random() < 0.3 ? ('bold' as const) : ('normal' as const),
                color: palette.text[Math.floor(random() * palette.text.length)],
                text: PHRASES[Math.floor(random() * PHRASES.length)],
            }
            const ink = await measureInk(run)
            const baseline = top - ink.top
            if (x + ink.left + ink.width > layout.width - margin || top + ink.height > rowBottomLimit) {
                continue
            }
            const button =
                random() < 0.12 ? palette.buttonFills[Math.floor(random() * palette.buttonFills.length)] : undefined
            if (button && button === run.color) {
                continue
            }
            runs.push({ ...run, x, baseline, buttonFill: button })
            runBoxes.push([x + ink.left, baseline + ink.top, x + ink.left + ink.width, baseline + ink.top + ink.height])
            for (const { text, ink: w } of await measureWordInks(run)) {
                words.push({
                    box: [x + w.left, baseline + w.top, x + w.left + w.width, baseline + w.top + w.height],
                    text,
                    fontPx,
                })
            }
            rowHeight = Math.max(rowHeight, ink.height)
            placed++
            x += ink.left + ink.width + Math.round(fontPx * (2 + random() * 6))
        }
        top += Math.max(rowHeight, fontPx) + Math.round(fontPx * (0.8 + random() * 1.4)) + (placed ? 0 : fontPx)
    }

    const buttons = runs
        .filter((r) => r.buttonFill)
        .map((r, i) => {
            const w = runBoxes[runs.indexOf(r)]
            const padX = Math.round(r.fontPx * 0.8)
            const padY = Math.round(r.fontPx * 0.45)
            return `<rect id="b${i}" x="${w[0] - padX}" y="${w[1] - padY}" width="${w[2] - w[0] + 2 * padX}" height="${w[3] - w[1] + 2 * padY}" rx="${padY}" fill="${r.buttonFill}"/>`
        })
    const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" width="${layout.width}" height="${layout.height}">` +
        palette.background +
        buttons.join('') +
        runs.map((r) => textElement(r, r.x, r.baseline)).join('') +
        '</svg>'
    const png = await sharp(Buffer.from(svg)).png().toBuffer()
    const file = `synthetic_${layout.name}_${seed}.png`
    return {
        png,
        gt: {
            file,
            width: layout.width,
            height: layout.height,
            words,
            tolerancePx: 0,
        },
    }
}

async function main(): Promise<void> {
    await mkdir(OUT, { recursive: true })
    const images: GtImage[] = []
    for (const layout of LAYOUTS) {
        for (let seed = FIRST_SEED; seed < FIRST_SEED + SEEDS_PER_LAYOUT; seed++) {
            const { png, gt } = await makeImage(layout, seed)
            await writeFile(OUT + gt.file, png)
            images.push(gt)
        }
    }
    await writeFile(OUT + 'gt.json', JSON.stringify(images))
    console.log(
        `${CALIBRATION ? 'calibration' : 'synthetic'}: ${images.length} images, ${images.reduce((n, im) => n + im.words.length, 0)} words in ${OUT}`
    )
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
