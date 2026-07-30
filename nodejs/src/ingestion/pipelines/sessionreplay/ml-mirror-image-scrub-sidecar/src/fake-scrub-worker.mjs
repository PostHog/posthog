// Stand-in worker for pool.test.ts: speaks the same protocol without loading any model. Plain .mjs
// so spawning it needs no TypeScript loader, which keeps the test measuring the pool rather than the
// runner. The input bytes select the behaviour.
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { parentPort, workerData } from 'node:worker_threads'

// failReadyOnce makes a slot's SECOND life die before signalling ready, so the first replacement of
// a dead worker fails and the pool has to keep retrying rather than lose the slot. The generation
// count lives on disk because each life is a fresh worker with no memory of the last.
if (workerData.failReadyOnce) {
    const marker = `${workerData.failReadyOnce}.${workerData.index}`
    const generation = existsSync(marker) ? Number(readFileSync(marker, 'utf8')) : 0
    writeFileSync(marker, String(generation + 1))
    if (generation === 1) {
        process.exit(9)
    }
}

parentPort.postMessage({ ready: true })

parentPort.on('message', async (job) => {
    const kind = Buffer.from(job.input).toString()
    if (kind === 'crash') {
        process.exit(7)
    }
    if (kind === 'hang') {
        // Never replies, standing in for a thread stuck inside a native ORT or libvips call. Cannot be
        // a real block (a busy loop or Atomics.wait) because then terminate() could not stop it either
        // and the test would hang on cleanup rather than assert anything.
        return
    }
    if (kind === 'undecodable') {
        parentPort.postMessage({ id: job.id, failure: { message: 'bad bytes', undecodable: true } })
        return
    }
    // Reports its own interval so the test can assert overlap directly rather than inferring
    // concurrency from total elapsed time, which turns into a flake on a loaded runner.
    const startedAt = performance.now()
    await new Promise((resolve) => setTimeout(resolve, 25))
    const finishedAt = performance.now()
    // Buffer.from(string) under 4 KiB comes out of Node's shared pool, which is the BLANK_PNG shape:
    // the backing ArrayBuffer is 8 KiB and is not transferable.
    const out =
        kind === 'pooled-buffer'
            ? Buffer.from('blank')
            : new Uint8Array(Buffer.from(`done:${kind}:w${workerData.index}`))
    // No transfer list, mirroring the real worker: a pool-backed ArrayBuffer cannot be transferred,
    // and attempting it would throw here rather than exercising the path under test.
    parentPort.postMessage({ id: job.id, out, timings: { totalMs: finishedAt - startedAt, startedAt, finishedAt } })
    if (kind === 'die-when-idle') {
        // Answers first, then dies holding no job: the pool has nothing to fail and has to notice
        // the loss on its own. Replacements get a different kind, so they stay healthy.
        setTimeout(() => process.exit(11), 5)
    }
})
