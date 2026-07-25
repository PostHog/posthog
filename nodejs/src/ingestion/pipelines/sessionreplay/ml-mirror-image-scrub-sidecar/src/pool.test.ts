import { UndecodableImageError } from './blur.ts'
import { type ScrubPool, type ScrubResult, startPool } from './pool.ts'

const FAKE_WORKER = new URL('./fake-scrub-worker.mjs', import.meta.url)

/** The stand-in worker reports its own interval on top of the real timings, so the test can assert
 *  overlap rather than infer it from elapsed wall time, which only measures how loaded the runner is. */
type TimedRun = ScrubResult['t'] & { startedAt: number; finishedAt: number }

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

    it('rebuilds an UndecodableImageError from the wire', async () => {
        // Structured clone drops the prototype, and this class is what the HTTP layer keys the
        // permanent 422 on. Lose it and every undecodable image becomes a retriable 500 that the
        // consumer then attempts four times.
        pool = await startPool(1, FAKE_WORKER)

        await expect(pool.scrub(Buffer.from('undecodable'))).rejects.toBeInstanceOf(UndecodableImageError)
    })

    it('fails the in-flight job when a worker dies, and keeps serving afterwards', async () => {
        // Otherwise the request hangs until the consumer's timeout and the pool quietly shrinks.
        pool = await startPool(2, FAKE_WORKER)

        await expect(pool.scrub(Buffer.from('crash'))).rejects.toThrow(/exited with code 7/)

        const after = await pool.scrub(Buffer.from('after'))
        expect(after.out.toString()).toMatch(/^done:after/)
    })
})
