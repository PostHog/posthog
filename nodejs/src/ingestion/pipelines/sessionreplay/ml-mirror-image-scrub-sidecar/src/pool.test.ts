import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

import { ImageOptOutError } from './image-input.ts'
import { ScrubAbandonedError, type ScrubPool, type ScrubResult, startPool } from './pool.ts'

// cwd-relative rather than import.meta, which jest's CJS transform cannot load (see qr.ts).
const FAKE_WORKER = pathToFileURL(`${process.cwd()}/src/fake-scrub-worker.mjs`)

/** The stand-in worker reports its own interval on top of the real timings, so the test can assert
 *  overlap rather than infer it from elapsed wall time, which only measures how loaded the runner is. */
type TimedRun = ScrubResult['t'] & { startedAt: number; finishedAt: number }

/** Replacement runs on a backoff timer, so tests wait for the pool to report the capacity back rather
 *  than for a duration that has to be re-tuned whenever that backoff changes. */
async function untilUsable(pool: ScrubPool, workers: number): Promise<void> {
    const giveUpAt = performance.now() + 10_000
    while (pool.usableWorkers() !== workers) {
        if (performance.now() > giveUpAt) {
            throw new Error(`pool stuck at ${pool.usableWorkers()} usable workers, wanted ${workers}`)
        }
        await new Promise((resolve) => setTimeout(resolve, 10))
    }
}

function peakOverlap(results: ScrubResult[]): number {
    const edges = results.flatMap((r) => [
        { at: (r.t as TimedRun).startedAt, delta: 1 },
        { at: (r.t as TimedRun).finishedAt, delta: -1 },
    ])
    edges.sort((a, b) => a.at - b.at || a.delta - b.delta)
    let live = 0
    let peak = 0
    for (const edge of edges) {
        live += edge.delta
        peak = Math.max(peak, live)
    }
    return peak
}

describe('startPool', () => {
    let pool: ScrubPool

    afterEach(async () => {
        await pool?.close()
    })

    it('runs a job on every worker at once instead of serialising them', async () => {
        // The whole reason the pool exists: onnxruntime-node's run blocks its thread, so concurrency
        // only comes from having several. If dispatch ever serialises, throughput collapses to one
        // image at a time and nothing else in the suite would notice.
        pool = await startPool(3, FAKE_WORKER)

        const results = await Promise.all(['a', 'b', 'c'].map((k) => pool.scrub(Buffer.from(k))))

        expect(peakOverlap(results)).toBe(3)
        expect(results.map((r) => r.out.toString().split(':')[1])).toEqual(['a', 'b', 'c'])
    })

    it('never exceeds the worker count, queueing the rest', async () => {
        // A job handed to a busy worker would be lost or would overwrite its in-flight reply, so the
        // ceiling matters as much as the parallelism.
        pool = await startPool(2, FAKE_WORKER)

        const results = await Promise.all(Array.from({ length: 6 }, (_unused, i) => pool.scrub(Buffer.from(`q${i}`))))

        expect(peakOverlap(results)).toBe(2)
        expect(results.map((r) => r.out.toString().split(':')[1])).toEqual(['q0', 'q1', 'q2', 'q3', 'q4', 'q5'])
    })

    it('replaces a worker that dies while idle', async () => {
        // A worker holding no job leaves nothing to reject, so a pool that only reacts to in-flight
        // failures loses it silently and never recovers the capacity. The only visible symptom would
        // be throughput quietly dropping, which is indistinguishable from the load easing off.
        pool = await startPool(2, FAKE_WORKER)

        // The worker answers before it dies, so wait for the loss itself and then for the recovery:
        // scrub() returning says nothing about whether the death has happened yet.
        await pool.scrub(Buffer.from('die-when-idle'))
        await untilUsable(pool, 1)
        await untilUsable(pool, 2)

        const results = await Promise.all(['x', 'y'].map((k) => pool.scrub(Buffer.from(k))))
        expect(peakOverlap(results)).toBe(2)
    })

    it('survives a reply whose buffer is pool-backed', async () => {
        // A small Buffer shares Node's 8 KiB pool, and that pool ArrayBuffer cannot be transferred.
        // BLANK_PNG is exactly this shape, so transferring the reply threw DataCloneError on the
        // NSFW-gated path, killing the worker and turning a successful blank into a retriable 500.
        pool = await startPool(1, FAKE_WORKER)

        const result = await pool.scrub(Buffer.from('pooled-buffer'))

        expect(result.out.length).toBeGreaterThan(0)
        const again = await pool.scrub(Buffer.from('still-alive'))
        expect(again.out.toString()).toMatch(/^done:still-alive/)
    })

    it('rebuilds an UndecodableImageError from the wire', async () => {
        // Structured clone drops the prototype, and this class is what the HTTP layer keys the
        // permanent 422 on. Lose it and every undecodable image becomes a retriable 500 that the
        // consumer then attempts four times.
        pool = await startPool(1, FAKE_WORKER)

        await expect(pool.scrub(Buffer.from('undecodable'))).rejects.toMatchObject({
            reason: 'decode_failed',
        })
    })

    it('rebuilds an ImageOptOutError from the wire', async () => {
        pool = await startPool(1, FAKE_WORKER)

        await expect(pool.scrub(Buffer.from('opt-out'))).rejects.toBeInstanceOf(ImageOptOutError)
    })

    it('drops a queued job whose caller has hung up, without occupying a worker', async () => {
        // The consumer gives up after 10s and retries, but its queue entry outlives it. Dispatching
        // it anyway spends a full scrub on a response nobody reads, and the server holds one of its
        // concurrency slots until that scrub settles, so a backlog of abandoned work sheds live
        // requests with 503s while the pool is busy with dead ones.
        pool = await startPool(1, FAKE_WORKER)
        const hungUp = new AbortController()

        // One worker, so everything after the first job waits in the queue behind it.
        const running = pool.scrub(Buffer.from('first'))
        const abandonedJob = pool.scrub(Buffer.from('abandoned'), hungUp.signal)
        const wanted = pool.scrub(Buffer.from('wanted'))
        hungUp.abort()

        await expect(abandonedJob).rejects.toBeInstanceOf(ScrubAbandonedError)
        expect((await running).out.toString()).toMatch(/^done:first/)
        expect((await wanted).out.toString()).toMatch(/^done:wanted/)
    })

    it('keeps retrying a replacement that cannot start', async () => {
        // spawn() writes its slot before it can know the worker is good, so an attempt that fails
        // leaves one that is never usable and never retired. If the failure is not retried, nothing
        // else ever will be: the slot is gone for the process's lifetime, the pod serves at reduced
        // capacity, and liveness only fails at zero usable workers so nothing restarts it.
        const dir = mkdtempSync(join(tmpdir(), 'scrub-pool-'))
        try {
            pool = await startPool(2, FAKE_WORKER, 5000, { failReadyOnce: join(dir, 'died') })
            await untilUsable(pool, 2)

            // Kill one worker. Its first replacement dies before signalling ready; the second must land.
            await expect(pool.scrub(Buffer.from('crash'))).rejects.toThrow(/exited with code 7/)
            await untilUsable(pool, 2)

            const results = await Promise.all(['x', 'y'].map((k) => pool.scrub(Buffer.from(k))))
            expect(peakOverlap(results)).toBe(2)
        } finally {
            rmSync(dir, { recursive: true, force: true })
        }
    })

    it('reclaims a worker that never replies, and keeps serving afterwards', async () => {
        // A thread stuck inside a native ORT or libvips call answers nothing and cannot be interrupted,
        // so without a deadline the job never settles. The server only decrements its concurrency count
        // when it does, which means one wedge permanently costs one of maxConcurrency: after enough of
        // them the sidecar sheds every request with a 503 until the pod is restarted.
        pool = await startPool(1, FAKE_WORKER, 100)

        await expect(pool.scrub(Buffer.from('hang'))).rejects.toThrow(/timed out/)

        await untilUsable(pool, 1)
        const after = await pool.scrub(Buffer.from('after'))
        expect(after.out.toString()).toMatch(/^done:after/)
    })

    it('fails the in-flight job when a worker dies, and keeps serving afterwards', async () => {
        // Otherwise the request hangs until the consumer's timeout and the pool quietly shrinks.
        pool = await startPool(2, FAKE_WORKER)

        await expect(pool.scrub(Buffer.from('crash'))).rejects.toThrow(/exited with code 7/)

        const after = await pool.scrub(Buffer.from('after'))
        expect(after.out.toString()).toMatch(/^done:after/)
    })
})
