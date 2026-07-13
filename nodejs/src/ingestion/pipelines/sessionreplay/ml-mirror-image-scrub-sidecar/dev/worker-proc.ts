/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * One worker process. Loads what MODE needs, processes WORK_N images, and writes the processing
 * window (excludes model load + warmup) as @@R@@{json} on stdout. Both modes pin sharp to one
 * libvips thread so a process ≈ one core, making the per-process numbers comparable and the
 * sum-over-processes a fair machine-throughput figure.
 *
 * MODE=blur     -> baseline blurOnly (no models, no network)
 * MODE=advanced -> nsfw + face + dbnet scrub
 */
import { readFile, readdir } from 'node:fs/promises'
import sharp from 'sharp'

import { advancedScrub, blurOnly, loadModels } from '../src/scrub.ts'

sharp.concurrency(1)

const N = Number(process.env.WORK_N ?? 40)
const MODE = process.env.MODE ?? 'advanced'

async function main(): Promise<void> {
    const files = (await readdir('corpus')).filter((f) => f.endsWith('.png'))
    const bufs = await Promise.all(files.map((f) => readFile('corpus/' + f)))

    let run: (b: Buffer) => Promise<unknown>
    if (MODE === 'blur') {
        run = (b) => blurOnly(b)
    } else {
        const models = await loadModels()
        run = (b) => advancedScrub(b, models, 'dbnet')
    }

    await run(bufs[0]) // warmup
    const t0 = performance.now()
    for (let i = 0; i < N; i++) {
        await run(bufs[i % bufs.length])
    }
    const ms = performance.now() - t0
    process.stdout.write('@@R@@' + JSON.stringify({ imgs: N, ms }))
}

main().catch((e) => {
    console.error(String(e))
    process.exit(1)
})
