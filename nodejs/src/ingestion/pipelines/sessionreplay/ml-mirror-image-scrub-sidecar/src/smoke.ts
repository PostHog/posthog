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
import { startPool } from './pool.ts'

const WORKER_URL = new URL('./scrub-worker.ts', import.meta.url)

/**
 * A rendered fixture, embedded as bytes rather than drawn here.
 *
 * Drawing text at build time needs a font, and the runtime image has no fontconfig: an SVG with a
 * `font-family` renders as an empty frame there, so the assertions below all fail on a scrub that is
 * working perfectly. Rendering once on a machine that has fonts and shipping the pixels keeps the
 * check honest without adding a font package to the image for the sake of one test.
 *
 * 320x180 with two lines of 22px text and a filled block, which reaches the detector well above its
 * measured floor at any plan the sidecar ships with.
 */
const TEXT_FIXTURE_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAMAAADSOgUjAAAC/VBMVEX///8SGSiQk5oxN0TAwcX8/Pynqq8RGCdBRlL+/v55fYVgZW/29veW' +
        'mqAYHi0qMD4TGinv8PG0t7vb3N4VHCp1eYL09PX9/f0jKTfu7/D6+vv4+fmSlZwWHSs2PEmeoacgJjX5+voUGyqrrbMXHSyAhIxeYmx+goqm' +
        'qa/T1Nf7+/x6foeIjJONkJhWW2Y9Q08kKjglKzna290aIS9kaXL39/cYHy5scHknLjve3+G6vMAfJjTs7e6Tlp3q6uzY2dvz8/QcIzEhJzVx' +
        'dX5FS1bh4uTm5+jAwsa5u7/19fZpbXfw8fEmLTry8vOxs7hwdH2qrbKvsbYbIjCgo6nOz9KlqK6wsrdZXmi4ur/k5eYeJTPq6+zd3uGEh4+C' +
        'ho1ARVFcYGtobHbo6Orn5+mjpasuNEF2eoKytbrW19pQVWApMD3CxMiipKplanPKy8/l5udSV2KKjpWPkplXXGcmLDooLzzc3d9CR1OVmJ6H' +
        'ipLc3eBfZG4dJDKprLHi4+WsrrTO0NPt7u+oq7A4PktVWmWIi5NRV2GbnqS8vsJESlYiKDa/wMXNztHIys1/g4u3ub5QVmFdYWzU1dgZIC/H' +
        'ycxCSFQsMkDDxcnX2Nt8gIj4+PjBw8c+Q1Dx8fKfoqh4fIQyOEXr7O00OkZLUFzLzNBOU17P0dRydn9NUl2OkZnZ2txPVF/GyMtqbndmanR3' +
        'e4M3PUp9gYmusLVjaHLp6etbYGo/RFGkp627vcHMzdAvNUK1t7w0Okduc3zQ0tWdoKZITVnFx8qGiZGXmqGytLnV1tmztrpUWWQwNkO2uL1h' +
        'ZnBTWGNHTVg6QEyDh47j5OYzOUXExspDSVWYm6I8Qk5na3U5P0tJTlpaX2mtr7SUl56kpqzS1NZscXpKT1t0eIHg4eNrb3iBhY2FiJA1O0jf' +
        '4OJtcnu+wMShpKl6fYZiZ3GLj5Zzd4DJys6anaTR09Wcn6W9v8NYXWeZnKNGTFcrMT9MUVyJjZSRlJuMkJeWmZ8tM0Bvc317f4g7QU0elTzO' +
        'AAAACXBIWXMAAAsTAAALEwEAmpwYAAAM10lEQVR42u2cd1hUxxqHZ5Hlxwqui640g8CGVcRGkSIqAoqKgIgKKIKIigoaFRv2etXYu8be9UZj' +
        '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' +
        'AAAASUVORK5CYII=',
    'base64'
)

async function main(): Promise<void> {
    const pool = await startPool(2, WORKER_URL)
    const png = TEXT_FIXTURE_PNG
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
