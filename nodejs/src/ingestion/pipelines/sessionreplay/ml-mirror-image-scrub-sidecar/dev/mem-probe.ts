/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Resident memory per worker, which is what WORKER_MEMORY_BUDGET_BYTES in src/cores.ts has to be set
 * from. That constant decides how many workers a pod runs, so guessing it low sizes the pool into an
 * OOM crash loop and guessing it high leaves cores idle.
 *
 *   tsx dev/mem-probe.ts <workers> [image]
 *
 * Peak RSS with every worker scrubbing at once, because that is the moment a pod dies: the models
 * and isolate are a small part of it, and the transient a scrub holds is most of it. Measure at the
 * SCRUB_MAX_PIXELS cap, where the transient plateaus.
 *
 * Measured on a 2026 dev machine at the then-current 2.56 MP cap: 278 MB/worker on a 0.33 MP frame,
 * 719 MB on 2 MP, 776 MB at the cap with the ONNX arena disabled (838 MB with it on). Re-run it
 * after any change to the cap, the arena setting, or what compose holds.
 */
import { readFile } from 'node:fs/promises'

import { startPool } from './pool-url.ts'

const rssMb = (): number => Math.round(process.memoryUsage.rss() / 1024 / 1024)

async function main(): Promise<void> {
    const size = Number(process.argv[2] ?? 1)
    const image = await readFile(process.argv[3] ?? 'corpus/shot_desktop_1920x1080_dpr1_0.png')
    const before = rssMb()
    const pool = await startPool(size)
    const loaded = rssMb()
    // All at once: a worker's peak overlaps its siblings' in production, and it is the sum the
    // kernel's OOM killer looks at.
    await Promise.all(Array.from({ length: size }, () => pool.scrub(image)))
    const peak = rssMb()
    await pool.close()
    console.log(
        `  workers=${String(size).padStart(2)}  baseline ${before}MB  after load ${loaded}MB  peak ${peak}MB  ` +
            `-> ${((peak - before) / size).toFixed(0)}MB/worker`
    )
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
