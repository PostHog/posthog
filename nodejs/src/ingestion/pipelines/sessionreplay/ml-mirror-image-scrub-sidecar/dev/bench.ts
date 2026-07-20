/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Throughput benchmark. Runs the corpus through three pipelines and reports images/sec, MB/sec,
 * p50/p95 latency, and the advanced per-stage breakdown:
 *   1. blur only            (current production baseline)
 *   2. advanced + heuristic (model-free edge-density text detection)
 *   3. advanced + dbnet     (native ONNX text detection)
 *
 * Usage: tsx src/bench.ts [--reps N]
 */
import { readFile, readdir } from 'node:fs/promises'
import { availableParallelism } from 'node:os'
import sharp from 'sharp'

import {
    type Models,
    type StageTimings,
    type TextMode,
    advancedScrub,
    blurOnly,
    disposeModels,
    loadModels,
} from '../src/scrub.ts'

// One libvips thread per sharp op, so image-level concurrency parallelizes across cores instead of
// each op grabbing every core and oversubscribing.
sharp.concurrency(1)

const OUT = new URL('../corpus/', import.meta.url).pathname
const reps = Number(process.argv.includes('--reps') ? process.argv[process.argv.indexOf('--reps') + 1] : 3)
const cores = availableParallelism()

function pct(xs: number[], p: number): number {
    const s = [...xs].sort((a, b) => a - b)
    return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))]
}
const sum = (xs: number[]): number => xs.reduce((a, b) => a + b, 0)
const fmt = (n: number): string => n.toFixed(1)

interface Img {
    f: string
    buf: Buffer
}
interface Result {
    mean: number
    throughput: number
    mbps: number
    p50: number
    p95: number
    stages: StageTimings[]
}

async function runAdvanced(images: Img[], models: Models, mode: TextMode, totalBytes: number): Promise<Result> {
    await advancedScrub(images[0].buf, models, mode) // warmup
    const lat: number[] = []
    const stages: StageTimings[] = []
    const t0 = performance.now()
    for (let r = 0; r < reps; r++) {
        for (const img of images) {
            const { t } = await advancedScrub(img.buf, models, mode)
            lat.push(t.totalMs)
            stages.push(t)
        }
    }
    const wall = (performance.now() - t0) / 1000
    return {
        mean: sum(lat) / lat.length,
        throughput: lat.length / wall,
        mbps: totalBytes / 1e6 / wall,
        p50: pct(lat, 50),
        p95: pct(lat, 95),
        stages,
    }
}

function reportAdvanced(label: string, r: Result, blanked: number, n: number): void {
    const avg = (k: keyof StageTimings): number => sum(r.stages.map((s) => s[k] as number)) / r.stages.length
    console.log(`=== ${label} ===`)
    console.log(`  throughput: ${fmt(r.throughput)} img/s/core   ${fmt(r.mbps)} MB/s`)
    console.log(`  latency:    p50 ${fmt(r.p50)}ms   p95 ${fmt(r.p95)}ms   mean ${fmt(r.mean)}ms`)
    console.log(
        `  blanked:    ${blanked}/${n}   avg faces ${fmt(avg('faces'))}   avg text boxes ${fmt(avg('textBoxes'))}`
    )
    console.log('  per-stage mean (ms):')
    console.log(`     decode  ${fmt(avg('decodeMs'))}   (image in)`)
    console.log(`     nsfw    ${fmt(avg('nsfwMs'))}`)
    console.log(`     face    ${fmt(avg('faceMs'))}`)
    console.log(`     text    ${fmt(avg('textMs'))}`)
    console.log(`     compose ${fmt(avg('composeMs'))}`)
    console.log(`     encode  ${fmt(avg('encodeMs'))}   (image out)\n`)
}

async function main(): Promise<void> {
    const files = (await readdir(OUT)).filter((f) => f.endsWith('.png'))
    const images = await Promise.all(files.map(async (f) => ({ f, buf: await readFile(OUT + f) })))
    const totalBytes = sum(images.map((i) => i.buf.length)) * reps
    const n = images.length * reps
    console.log(
        `corpus: ${images.length} images, ${reps} reps = ${n} runs, ${(totalBytes / 1e6).toFixed(1)} MB total\n`
    )

    // --- 1. baseline: blur only ---
    await blurOnly(images[0].buf)
    const blat: number[] = []
    const bt0 = performance.now()
    for (let r = 0; r < reps; r++) {
        for (const img of images) {
            const t = performance.now()
            await blurOnly(img.buf)
            blat.push(performance.now() - t)
        }
    }
    const bwall = (performance.now() - bt0) / 1000
    const blurMean = sum(blat) / blat.length
    const blurThroughput = blat.length / bwall
    console.log('=== BLUR ONLY (current production baseline) ===')
    console.log(`  throughput: ${fmt(blurThroughput)} img/s/core   ${fmt(totalBytes / 1e6 / bwall)} MB/s`)
    console.log(`  latency:    p50 ${fmt(pct(blat, 50))}ms   p95 ${fmt(pct(blat, 95))}ms   mean ${fmt(blurMean)}ms\n`)

    // --- 2 + 3. advanced ---
    console.log('loading models (nsfw + yunet + dbnet)...')
    const tLoad = performance.now()
    const models = await loadModels()
    console.log(`  models loaded in ${fmt((performance.now() - tLoad) / 1000)}s\n`)

    const db = await runAdvanced(images, models, 'dbnet', totalBytes)
    reportAdvanced('ADVANCED + DBNET text (native ONNX detection), single image at a time', db, 0, n)

    // --- concurrency sweep: how much overlaps when we process images in parallel? ---
    // sharp + the three ORT sessions run async on libuv worker threads
    // thread, so it can't overlap in-process. This sweep shows the ceiling of in-process async.
    console.log(`=== CONCURRENCY SWEEP (in-process async, ${cores} cores available) ===`)
    let best = db.throughput
    for (const c of [1, 2, 4, 8].filter((c) => c <= cores * 2)) {
        const tp = await throughputAt(images, models, c)
        best = Math.max(best, tp)
        console.log(`  concurrency ${c}: ${fmt(tp)} img/s  (${fmt(tp / db.throughput)}x vs serial)`)
    }

    await disposeModels(models)

    // --- headline ---
    const dbScrub = db.mean - avgOf(db, 'decodeMs') - avgOf(db, 'encodeMs')
    console.log('\n=== HEADLINE (native: onnxruntime-node) ===')
    console.log(`  blur baseline:    ${fmt(blurMean)}ms/img   ${fmt(blurThroughput)} img/s/core`)
    console.log(
        `  advanced (dbnet): ${fmt(db.mean)}ms/img   ${fmt(db.throughput)} img/s/core   ${fmt(db.mean / blurMean)}x blur`
    )
    console.log(
        `  dbnet job: scrub ${fmt((dbScrub / db.mean) * 100)}%  |  decode+encode ${fmt(((avgOf(db, 'decodeMs') + avgOf(db, 'encodeMs')) / db.mean) * 100)}%`
    )
    console.log(`  best in-process throughput: ${fmt(best)} img/s (async overlap of sharp+ORT)`)
    console.log(`  for full machine scaling use worker_threads/processes,`)
    console.log(`  ~${fmt(db.throughput)} img/s/core x ${cores} cores ≈ ${fmt(db.throughput * cores)} img/s/box.`)
}

async function throughputAt(images: Img[], models: Models, c: number): Promise<number> {
    const tasks: Buffer[] = []
    for (let r = 0; r < reps; r++) {
        for (const img of images) {
            tasks.push(img.buf)
        }
    }
    let idx = 0
    const worker = async (): Promise<void> => {
        for (;;) {
            const i = idx++
            if (i >= tasks.length) {
                return
            }
            await advancedScrub(tasks[i], models, 'dbnet')
        }
    }
    const t0 = performance.now()
    await Promise.all(Array.from({ length: c }, () => worker()))
    return tasks.length / ((performance.now() - t0) / 1000)
}

function avgOf(r: Result, k: keyof StageTimings): number {
    return sum(r.stages.map((s) => s[k] as number)) / r.stages.length
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
