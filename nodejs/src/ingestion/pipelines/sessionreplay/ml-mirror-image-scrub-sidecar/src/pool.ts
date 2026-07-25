/* eslint-disable no-console -- sidecar logs to stdout */
import { Worker } from 'node:worker_threads'

import { UndecodableImageError } from './blur.ts'
import { type StageTimings } from './scrub.ts'
import { type ScrubReply } from './worker-protocol.ts'

const RESTART_BACKOFF_BASE_MS = 500
const RESTART_BACKOFF_MAX_MS = 30_000

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
    /** False until the worker reports ready and again once retired. A worker that never finished
     *  starting will not answer, so dispatching to it strands the job until the consumer times out. */
    usable: boolean
    /** A crash raises both `error` and `exit`, so replacement has to be idempotent per slot. */
    retired: boolean
}

/**
 * A fixed set of inference workers, one job each at a time.
 *
 * Resolves only once every worker has loaded its models, so a worker that cannot start (a missing
 * model, or a loader that does not reach worker threads) fails startup loudly rather than leaving
 * the pool quietly short-handed. That matters because the listener is bound after this returns, so
 * the readiness probe never passes on a broken pool.
 *
 * The worker URL is a parameter rather than resolved here because jest's CJS transform cannot load a
 * module containing import.meta, the same constraint qr.ts documents. Entry points run under tsx,
 * where it works.
 */
export async function startPool(size: number, workerUrl: URL): Promise<ScrubPool> {
    const slots: Slot[] = []
    const queue: { id: number; input: Buffer; pending: Pending }[] = []
    let nextJobId = 0
    let closing = false
    const restartFailures: number[] = []

    const pump = (): void => {
        if (closing) {
            return
        }
        for (const slot of slots) {
            if (!slot?.usable || slot.job || queue.length === 0) {
                continue
            }
            const next = queue.shift()!
            slot.job = { id: next.id, pending: next.pending }
            slot.worker.postMessage({ id: next.id, input: next.input })
        }
    }

    const spawn = async (index: number): Promise<void> => {
        const worker = new Worker(workerUrl, { workerData: { index } })
        const slot: Slot = { worker, job: null, usable: false, retired: false }
        slots[index] = slot

        // Startup failures reject rather than retire, so a worker that cannot load fails startPool
        // instead of respawning forever against whatever is broken.
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
            if ('ready' in msg) {
                return
            }
            if (!slot.job || slot.job.id !== msg.id) {
                // Should be unreachable: one job per slot, replies keyed by id. If it ever happens the
                // job it belonged to never settles, which strands a concurrency slot in the server for
                // the process's lifetime, so say so rather than drop it silently.
                console.error(`[image-scrub] worker ${index} replied for job ${msg.id} with none in flight`)
                return
            }
            const { pending } = slot.job
            slot.job = null
            restartFailures[index] = 0
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

        // A worker that dies takes any in-flight job with it, so fail that request rather than let it
        // hang until the consumer's timeout. Replacement is unconditional: a worker that dies while
        // idle carries no job to fail, and leaving it would shrink the pool with nothing to show it.
        worker.on('error', (error) => retireAndReplace(index, slot, error))
        worker.on('exit', (code) => retireAndReplace(index, slot, new Error(`scrub worker exited with code ${code}`)))
        slot.usable = true
    }

    const retireAndReplace = (index: number, slot: Slot, error: Error): void => {
        if (closing || slot.retired) {
            return
        }
        slot.retired = true
        slot.usable = false
        slot.job?.pending.reject(error)
        slot.job = null
        void slot.worker.terminate().catch(() => {})

        // Backoff, because a worker that dies on every start (an OOM loading models, a corrupt model
        // file) would otherwise respawn in a tight loop, spending the CPU the survivors need and
        // burying the first failure in log noise. Reset once a replacement completes a job.
        const failures = (restartFailures[index] ?? 0) + 1
        restartFailures[index] = failures
        const delayMs = Math.min(RESTART_BACKOFF_MAX_MS, RESTART_BACKOFF_BASE_MS * 2 ** (failures - 1))
        console.error(
            `[image-scrub] worker ${index} died (${failures} in a row), replacing in ${delayMs}ms: ${error.message}`
        )
        const timer = setTimeout(() => {
            if (closing) {
                return
            }
            spawn(index)
                .then(pump)
                .catch((e: unknown) => console.error(`[image-scrub] worker ${index} could not restart: ${String(e)}`))
        }, delayMs)
        timer.unref()
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
            for (const pendingJob of queue.splice(0)) {
                pendingJob.pending.reject(new Error('scrub pool is closing'))
            }
            // Slots can be absent while a replacement is still waiting out its backoff.
            for (const slot of slots) {
                slot?.job?.pending.reject(new Error('scrub pool is closing'))
            }
            await Promise.all(slots.filter(Boolean).map((s) => s.worker.terminate()))
        },
    }
}
