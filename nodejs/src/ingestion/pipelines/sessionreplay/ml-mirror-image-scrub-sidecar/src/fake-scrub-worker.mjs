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
    // Long enough that a pool running jobs serially takes visibly longer than one running them at once.
    const jobMs = 40
    await new Promise((resolve) => setTimeout(resolve, jobMs))
    const out = new Uint8Array(Buffer.from(`done:${kind}:w${workerData.index}`))
    parentPort.postMessage({ id: job.id, out, timings: { totalMs: jobMs } }, [out.buffer])
})
