/* eslint-disable no-console -- sidecar logs to stdout */
import { Worker } from 'node:worker_threads'

import { UndecodableImageError } from './blur.ts'
import { type StageTimings } from './scrub.ts'
import { type ScrubReply } from './worker-protocol.ts'

const WORKER_URL = new URL('./scrub-worker.ts', import.meta.url)

export interface ScrubResult {
    out: Buffer
    t: StageTimings
}

export interface ScrubPool {
    scrub(input: Buffer): Promise<ScrubResult>
    close(): Promise<void>
}

interface Pending {
    resolve: (r: ScrubResult) => void
    reject: (e: Error) => void
}

interface Slot {
    worker: Worker
    /** The job this worker is running, since it takes exactly one at a time: `run` blocks its thread. */
    job: { id: number; pending: Pending } | null
}

/**
 * A fixed set of inference workers, one job each at a time.
 *
 * Resolves only once every worker has loaded its models, so a worker that cannot start (a missing
 * model, or a loader that does not reach worker threads) fails startup loudly rather than leaving
 * the pool quietly short-handed. That matters because the listener is bound after this returns, so
 * the readiness probe never passes on a broken pool.
 */
export async function startPool(size: number, workerUrl: URL = WORKER_URL): Promise<ScrubPool> {
    const slots: Slot[] = []
    const queue: { id: number; input: Buffer; pending: Pending }[] = []
    let nextJobId = 0
    let closing = false

    const pump = (): void => {
        if (closing) {
            return
        }
        for (const slot of slots) {
            if (slot.job || queue.length === 0) {
                continue
            }
            const next = queue.shift()!
            slot.job = { id: next.id, pending: next.pending }
            slot.worker.postMessage({ id: next.id, input: next.input })
        }
    }

    const spawn = async (index: number): Promise<void> => {
        const worker = new Worker(workerUrl, { workerData: { index } })
        const slot: Slot = { worker, job: null }
        slots[index] = slot

        await new Promise<void>((ready, failed) => {
            const onReady = (msg: ScrubReply): void => {
                if ('ready' in msg) {
                    worker.off('message', onReady)
                    worker.off('error', failed)
                    ready()
                }
            }
            worker.on('message', onReady)
            worker.once('error', failed)
        })

        worker.on('message', (msg: ScrubReply) => {
            if ('ready' in msg || !slot.job || slot.job.id !== msg.id) {
                return
            }
            const { pending } = slot.job
            slot.job = null
            if ('failure' in msg) {
                const error = msg.failure.undecodable
                    ? new UndecodableImageError(msg.failure.message)
                    : new Error(msg.failure.message)
                pending.reject(error)
            } else {
                pending.resolve({
                    out: Buffer.from(msg.out.buffer, msg.out.byteOffset, msg.out.byteLength),
                    t: msg.timings,
                })
            }
            pump()
        })

        // A worker that dies takes its in-flight job with it, so fail that request rather than let it
        // hang until the consumer's timeout, and replace the worker or the pool shrinks silently.
        worker.on('error', (error) => failSlotAndReplace(index, slot, error))
        worker.on('exit', (code) => {
            if (!closing && slot.job) {
                failSlotAndReplace(index, slot, new Error(`scrub worker exited with code ${code}`))
            }
        })
    }

    const failSlotAndReplace = (index: number, slot: Slot, error: Error): void => {
        if (closing) {
            return
        }
        slot.job?.pending.reject(error)
        slot.job = null
        console.error(`[image-scrub] worker ${index} died, replacing: ${error.message}`)
        void slot.worker.terminate().catch(() => {})
        spawn(index)
            .then(pump)
            .catch((e: unknown) => console.error(`[image-scrub] worker ${index} could not restart: ${String(e)}`))
    }

    await Promise.all(Array.from({ length: size }, (_unused, i) => spawn(i)))

    return {
        scrub(input: Buffer): Promise<ScrubResult> {
            if (closing) {
                return Promise.reject(new Error('scrub pool is closing'))
            }
            return new Promise<ScrubResult>((resolve, reject) => {
                queue.push({ id: nextJobId++, input, pending: { resolve, reject } })
                pump()
            })
        },
        async close(): Promise<void> {
            closing = true
            for (const { job } of slots) {
                job?.pending.reject(new Error('scrub pool is closing'))
            }
            await Promise.all(slots.map((s) => s.worker.terminate()))
        },
    }
}
