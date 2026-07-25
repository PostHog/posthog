import { UndecodableImageError } from './blur.ts'
import { type ScrubPool, startPool } from './pool.ts'

const FAKE_WORKER = new URL('./fake-scrub-worker.mjs', import.meta.url)
const JOB_MS = 40

describe('startPool', () => {
    let pool: ScrubPool

    afterEach(async () => {
        await pool?.close()
    })

    it('runs one job per worker at once instead of serialising them', async () => {
        // The whole reason the pool exists: onnxruntime-node's run blocks its thread, so concurrency
        // has to come from having several threads. If dispatch ever serialises, throughput silently
        // collapses to one image at a time and nothing else in the suite would notice.
        pool = await startPool(3, FAKE_WORKER)

        const started = Date.now()
        const results = await Promise.all(['a', 'b', 'c'].map((k) => pool.scrub(Buffer.from(k))))
        const elapsed = Date.now() - started

        expect(elapsed).toBeLessThan(JOB_MS * 2)
        expect(results.map((r) => r.out.toString().split(':')[1])).toEqual(['a', 'b', 'c'])
        expect(new Set(results.map((r) => r.out.toString().split(':')[2])).size).toBe(3)
    })

    it('queues past the worker count rather than dropping or overlapping jobs', async () => {
        pool = await startPool(2, FAKE_WORKER)

        const started = Date.now()
        const results = await Promise.all(Array.from({ length: 4 }, (_unused, i) => pool.scrub(Buffer.from(`q${i}`))))
        const elapsed = Date.now() - started

        expect(elapsed).toBeGreaterThanOrEqual(JOB_MS * 2)
        expect(results.map((r) => r.out.toString().split(':')[1])).toEqual(['q0', 'q1', 'q2', 'q3'])
    })

    it('rebuilds an UndecodableImageError from the wire', async () => {
        // Structured clone drops the prototype, and this class is what the HTTP layer keys the
        // permanent 422 on. Lose it and every undecodable image becomes a retriable 500 instead.
        pool = await startPool(1, FAKE_WORKER)

        await expect(pool.scrub(Buffer.from('undecodable'))).rejects.toBeInstanceOf(UndecodableImageError)
    })

    it('fails the in-flight job when a worker dies, and keeps serving afterwards', async () => {
        // Without this the request hangs until the consumer's timeout and the pool quietly shrinks.
        pool = await startPool(2, FAKE_WORKER)

        await expect(pool.scrub(Buffer.from('crash'))).rejects.toThrow(/exited with code 7/)

        const after = await pool.scrub(Buffer.from('after'))
        expect(after.out.toString()).toMatch(/^done:after/)
    })
})
