// Renders the stills from reel-capture.mjs into the PNG frames of a feature reel.
// Loads reel-template.html, steps its render(t) through time and screenshots each frame
// at 2x, so the reel stays sharp on high-density screens.
// Encode the frames with `annotate-evidence.py animate --frames-dir`.
//
// Usage: node reel-render.mjs <capture-dir> <frames-dir>
import { mkdirSync, readdirSync, readFileSync, rmSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

// Resolve Playwright from the PostHog checkout the command runs in, since the skill can live outside it.
const { chromium } = createRequire(path.join(process.cwd(), 'package.json'))('playwright')

const OUTPUT_SCALE = 2
// annotate-evidence.py animate --frames-dir defaults to the same rate.
const FPS = 15
const TEMPLATE = new URL('./reel-template.html', import.meta.url).href
const FRAME_NAME = /^\d{4}\.png$/

async function main() {
    const [captureDir, framesDir] = process.argv.slice(2)
    if (!captureDir || !framesDir) {
        throw new Error('Usage: node reel-render.mjs <capture-dir> <frames-dir>')
    }
    if (path.resolve(captureDir) === path.resolve(framesDir)) {
        // The encoder takes every PNG in the frames folder, so the stills would end up in the reel.
        throw new Error('Use a frames folder other than the capture folder')
    }
    const capture = JSON.parse(readFileSync(path.join(captureDir, 'frames.json'), 'utf8'))
    const data = {
        viewport: capture.viewport,
        frames: capture.frames.map((frame) => ({
            ...frame,
            src: pathToFileURL(path.resolve(captureDir, frame.file)).href,
        })),
    }
    mkdirSync(framesDir, { recursive: true })
    // A shorter re-render would otherwise leave old frames at the end of the reel.
    for (const name of readdirSync(framesDir).filter((name) => FRAME_NAME.test(name))) {
        rmSync(path.join(framesDir, name))
    }

    const browser = await chromium.launch()
    const page = await browser.newPage({ deviceScaleFactor: OUTPUT_SCALE })
    await page.goto(TEMPLATE)
    const { duration, width, height } = await page.evaluate((reelData) => window.setupReel(reelData), data)
    await page.setViewportSize({ width, height })

    const total = Math.ceil(duration * FPS)
    const reel = page.locator('#reel')
    for (let i = 0; i < total; i++) {
        await page.evaluate((t) => window.reel.render(t), i / FPS)
        await reel.screenshot({ path: path.join(framesDir, `${String(i).padStart(4, '0')}.png`) })
    }
    await browser.close()
    process.stdout.write(`${framesDir}: ${total} frames, ${duration.toFixed(1)}s at ${FPS} fps\n`)
}

await main()
