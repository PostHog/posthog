/**
 * Startup smoke test: loads the models, asserts the native tfjs backend, and runs one scrub end to
 * end. Run at image-build time (see Dockerfile.ml-mirror-image-scrub) with networking disabled, so
 * a missing/corrupt model, a prebuilt-binary mismatch, or an accidental runtime network dependency
 * fails the build instead of crash-looping the deploy.
 */
import sharp from 'sharp'

import './polyfill.ts'
import { advancedScrub, disposeModels, loadModels, tfjsBackend } from './scrub.ts'

async function main(): Promise<void> {
    const models = await loadModels()
    if (tfjsBackend() !== 'tensorflow') {
        throw new Error(`native tfjs backend failed to load, got '${tfjsBackend()}'`)
    }
    const png = await sharp({ create: { width: 64, height: 64, channels: 3, background: '#fff' } })
        .png()
        .toBuffer()
    const { t } = await advancedScrub(png, models)
    await disposeModels(models)
    console.log(`smoke scrub OK (backend=tensorflow, ${Math.round(t.totalMs)}ms)`)
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
