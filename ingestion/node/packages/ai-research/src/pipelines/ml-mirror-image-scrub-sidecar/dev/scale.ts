/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Multi-process scaling test for BOTH pipelines under the same one-core-per-process pin, so the
 * blur baseline and the advanced path are measured identically and the ratio holds at machine scale.
 * Spawns W workers (each its own process), each grinds WORK_N images; aggregate img/s =
 * sum(imgs) / max(processing-window).
 *
 * Usage: tsx src/scale.ts [w1 w2 ...]   (default: 1 4 8 12)
 */
import { spawn } from 'node:child_process'
import { availableParallelism } from 'node:os'

const WORK_N = process.env.WORK_N ?? '40'
const widths = process.argv
    .slice(2)
    .map(Number)
    .filter((n) => n > 0)
const levels = widths.length ? widths : [1, 4, 8, 12]
const cores = availableParallelism()

function runWorker(mode: string): Promise<{ imgs: number; ms: number }> {
    return new Promise((resolve, reject) => {
        const p = spawn('npx', ['tsx', 'dev/worker-proc.ts'], {
            env: {
                ...process.env,
                MODE: mode,
                WORK_N,
                // pin every native thread pool to 1 so each worker process ≈ one core
                TF_NUM_INTRAOP_THREADS: '1',
                TF_NUM_INTEROP_THREADS: '1',
                OMP_NUM_THREADS: '1',
                OPENBLAS_NUM_THREADS: '1',
                ORT_THREADS: '1',
                UV_THREADPOOL_SIZE: '2',
            },
        })
        let out = ''
        let err = ''
        p.stdout.on('data', (d) => (out += d))
        p.stderr.on('data', (d) => (err += d))
        p.on('close', (code) => {
            const m = out.indexOf('@@R@@')
            if (code !== 0 || m < 0) {
                return reject(new Error(`worker exited ${code}: ${err.slice(-200)}`))
            }
            resolve(JSON.parse(out.slice(m + 5).trim()))
        })
    })
}

async function sweep(mode: string): Promise<number> {
    console.log(`\n=== ${mode.toUpperCase()} (one core per process) ===`)
    let single = 0
    let best = 0
    for (const w of levels) {
        const results = await Promise.all(Array.from({ length: w }, () => runWorker(mode)))
        const imgs = results.reduce((s, r) => s + r.imgs, 0)
        const maxMs = Math.max(...results.map((r) => r.ms))
        const agg = imgs / (maxMs / 1000)
        if (w === 1) {
            single = agg
        }
        best = Math.max(best, agg)
        console.log(
            `  ${String(w).padStart(2)} procs: ${agg.toFixed(1).padStart(7)} img/s   (${(agg / single).toFixed(1)}x vs 1 proc)`
        )
    }
    return best
}

async function main(): Promise<void> {
    console.log(`machine: ${cores} cores; each worker processes ${WORK_N} images`)
    const blur = await sweep('blur')
    const adv = await sweep('advanced')
    console.log(`\n=== RATIO at machine scale ===`)
    console.log(`  blur peak ${blur.toFixed(0)} img/s   advanced peak ${adv.toFixed(0)} img/s`)
    console.log(`  advanced costs ${(blur / adv).toFixed(1)}x the blur baseline at full machine utilization.`)
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
