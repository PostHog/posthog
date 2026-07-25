import sharp from 'sharp'

import { advancedScrub, loadModels } from './src/scrub.ts'

const rss = () => Math.round(process.memoryUsage.rss() / 1024 / 1024)
async function noisy(w: number, h: number) {
    const px = Buffer.alloc(w * h * 3, 240)
    for (let i = 0; i < px.length; i += 13) px[i] = (i * 37) & 255
    return sharp(px, { raw: { width: w, height: h, channels: 3 } })
        .png({ compressionLevel: 1 })
        .toBuffer()
}
async function main() {
    const m = await loadModels()
    for (const [w, h] of [
        [1920, 1080],
        [8000, 60],
        [100000, 10],
        [400000, 4],
    ] as [number, number][]) {
        const png = await noisy(w, h)
        const before = rss()
        let peak = before
        const t = setInterval(() => {
            peak = Math.max(peak, rss())
        }, 2)
        const t0 = performance.now()
        try {
            const { t: tm } = await advancedScrub(png, m)
            const ms = performance.now() - t0
            clearInterval(t)
            peak = Math.max(peak, rss())
            console.log(
                `${w}x${h} png ${(png.length / 1e6).toFixed(1)}MB -> ${ms.toFixed(0)}ms  rss ${before}->${peak}MB (delta ${peak - before}MB)  boxes=${tm.textBoxes} stored=${tm.storedPixels}`
            )
        } catch (e) {
            clearInterval(t)
            console.log(`${w}x${h} FAILED ${String(e).slice(0, 120)}  rss peak ${Math.max(peak, rss())}MB`)
        }
    }
}
main().catch((e) => {
    console.error(e)
    process.exit(1)
})
