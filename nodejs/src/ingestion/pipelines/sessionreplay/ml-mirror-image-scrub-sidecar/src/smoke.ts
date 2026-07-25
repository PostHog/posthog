/**
 * Startup smoke test: starts the worker pool and runs two scrubs end to end. Run at image-build time
 * (see Dockerfile.ml-mirror-image-scrub) with networking disabled, so a missing/corrupt model, a
 * prebuilt-binary mismatch, or an accidental runtime network dependency fails the build instead of
 * crash-looping the deploy.
 *
 * It goes through the pool rather than calling advancedScrub directly so the build also proves the
 * runner's TypeScript loader reaches worker threads. Nothing else here would catch that, and its
 * failure mode is a pod that never becomes ready.
 */
import sharp from 'sharp'

import { startPool } from './pool.ts'

async function main(): Promise<void> {
    const pool = await startPool(2)
    const png = await sharp({ create: { width: 64, height: 64, channels: 3, background: '#fff' } })
        .png()
        .toBuffer()
    // Two at once, so the build fails if a second worker cannot start or the pool mis-routes replies.
    const [first, second] = await Promise.all([pool.scrub(png), pool.scrub(png)])
    if (first.out.length === 0 || second.out.length === 0) {
        throw new Error('smoke scrub produced empty output')
    }
    await pool.close()
    console.log(`smoke scrub OK (${Math.round(first.t.totalMs)}ms, ${Math.round(second.t.totalMs)}ms)`)
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
