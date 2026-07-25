// Stand-in worker for pool.test.ts: speaks the same protocol without loading any model. Plain .mjs
// so spawning it needs no TypeScript loader, which keeps the test measuring the pool rather than the
// runner. The input bytes select the behaviour.
import { parentPort, workerData } from 'node:worker_threads'

parentPort.postMessage({ ready: true })

parentPort.on('message', async (job) => {
    const kind = Buffer.from(job.input).toString()
    if (kind === 'crash') {
        process.exit(7)
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
    const out = new Uint8Array(Buffer.from(`done:${kind}:w${workerData.index}`))
    parentPort.postMessage({ id: job.id, out, timings: { totalMs: finishedAt - startedAt, startedAt, finishedAt } }, [
        out.buffer,
    ])
    if (kind === 'die-when-idle') {
        // Answers first, then dies holding no job: the pool has nothing to fail and has to notice
        // the loss on its own. Replacements get a different kind, so they stay healthy.
        setTimeout(() => process.exit(11), 5)
    }
})
