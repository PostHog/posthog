/**
 * Startup smoke test: starts the worker pool and runs two scrubs end to end. Run at image-build time
 * (see Dockerfile.ml-mirror-image-scrub) with networking disabled, so a missing/corrupt model, a
 * prebuilt-binary mismatch, or an accidental runtime network dependency fails the build instead of
 * crash-looping the deploy.
 *
 * It goes through the pool rather than calling advancedScrub directly so the build also proves the
 * runner's TypeScript loader reaches worker threads. Nothing else here would catch that, and its
 * failure mode is a pod that never becomes ready.
 *
 * The input has to carry content, and the result is asserted rather than just checked for bytes.
 * A flat frame takes the uniform fast path, which returns before the safety gate and all three
 * detectors: with one the build would still pass while running no inference at all, so an ONNX
 * binary that loads but cannot `run`, or a zxing wasm module that never instantiates, would reach
 * production. Text is the assertion because it exercises the longest path, DBNet through to the
 * composite, and it is the detector whose output the scrub mostly consists of.
 */
import sharp from 'sharp'

import { startPool } from './pool.ts'

const WORKER_URL = new URL('./scrub-worker.ts', import.meta.url)

/** Dark text on light, big enough to detect at any DET_FACTOR, plus a filled block so the composite
 *  has more than one region to merge. */
function contentPng(): Promise<Buffer> {
    return sharp(
        Buffer.from(
            `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">
               <rect width="640" height="360" fill="#ffffff"/>
               <rect x="24" y="24" width="240" height="64" fill="#111827"/>
               <text x="32" y="180" font-family="Arial" font-size="34" fill="#111827">Account 0098761234</text>
               <text x="32" y="240" font-family="Arial" font-size="34" fill="#111827">jane.doe@example.com</text>
             </svg>`
        )
    )
        .png()
        .toBuffer()
}

async function main(): Promise<void> {
    const pool = await startPool(2, WORKER_URL)
    const png = await contentPng()
    // Two at once, so the build fails if a second worker cannot start or the pool mis-routes replies.
    const [first, second] = await Promise.all([pool.scrub(png), pool.scrub(png)])
    await pool.close()

    for (const [label, result] of [
        ['first', first],
        ['second', second],
    ] as const) {
        if (result.out.length === 0) {
            throw new Error(`smoke scrub (${label}) produced empty output`)
        }
        if (result.t.uniform) {
            throw new Error(`smoke scrub (${label}) took the uniform fast path, so no model ran`)
        }
        if (result.t.blanked) {
            throw new Error(`smoke scrub (${label}) was blanked by the safety gate on a text fixture`)
        }
        if (result.t.textBoxes === 0) {
            throw new Error(`smoke scrub (${label}) found no text in a fixture that is mostly text`)
        }
    }
    console.log(
        `smoke scrub OK (${Math.round(first.t.totalMs)}ms, ${Math.round(second.t.totalMs)}ms, ` +
            `${first.t.textBoxes} text regions)`
    )
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
