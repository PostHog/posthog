/* eslint-disable no-console -- sidecar logs to stdout */
import { Worker } from 'node:worker_threads'

import { UndecodableImageError } from './blur.ts'
import { WORKER_HEAP_MB } from './cores.ts'
import { ImageOptOutError } from './image-input.ts'
import { ScrubMetrics } from './metrics.ts'
import { type StageTimings } from './scrub.ts'
import { type ScrubReply } from './worker-protocol.ts'

const WORKER_READY_TIMEOUT_MS = 120_000
const RESTART_BACKOFF_BASE_MS = 500
const RESTART_BACKOFF_MAX_MS = 30_000
/** How long a replacement must stay up before its slot's failure streak is forgiven. */
const RESTART_HEALTHY_MS = 60_000
/** How long a retired worker may take to terminate before that is worth a log line. */
const TERMINATE_GRACE_MS = 30_000

/** Nobody was waiting for this job by the time it could have run, so it was never dispatched. Not a
 *  failure of the scrub: the caller has already moved on. */
export class ScrubAbandonedError extends Error {}

export interface ScrubResult {
    out: Buffer
    t: StageTimings
}

export interface ScrubPool {
    /** `signal` is the caller's, so a job whose requester has already hung up is dropped from the
     *  queue instead of being dispatched. A job already running cannot be cancelled: its worker is
     *  inside a native call that does not observe signals. */
    scrub(input: Buffer, signal?: AbortSignal): Promise<ScrubResult>
    /** Workers alive and able to serve, busy ones included. The liveness probe reads this: with
     *  inference off the main thread, a process whose workers are all dead still answers probes
     *  perfectly well. */
    usableWorkers(): number
    queueDepth(): number
    close(): Promise<void>
}

interface Pending {
    resolve: (r: ScrubResult) => void
    reject: (e: Error) => void
}

interface Slot {
    worker: Worker
    /** The job this worker is running, since it takes exactly one at a time: `run` blocks its thread.
     *  `deadline` is armed here rather than at enqueue so it measures execution, not queue wait. */
    job: { id: number; pending: Pending; deadline: NodeJS.Timeout } | null
    /** False until the worker reports ready and again once retired. A worker that never finished
     *  starting will not answer, so dispatching to it strands the job until the consumer times out. */
    usable: boolean
    /** A crash raises both `error` and `exit`, so replacement has to be idempotent per slot. */
    retired: boolean
    /** When this worker became ready, so the restart backoff can tell a worker that recovered from
     *  one that is flapping. */
    readyAt: number
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
export async function startPool(
    size: number,
    workerUrl: URL,
    jobTimeoutMs = 15_000,
    workerData: Record<string, unknown> = {}
): Promise<ScrubPool> {
    const slots: Slot[] = []
    const queue: { id: number; input: Buffer; pending: Pending; signal?: AbortSignal; queuedAt: number }[] = []
    let nextJobId = 0
    let closing = false
    const restartFailures: number[] = []

    const pump = (): void => {
        if (closing) {
            return
        }
        // Drop from the front anything nobody is waiting for any more, before looking for a worker.
        // The consumer gives up on a request after 10s and retries, but its queue entry outlived it:
        // the job would still be dispatched, occupy a worker for a full scrub, and hold one of the
        // server's concurrency slots the whole time, so a backlog of abandoned work would shed live
        // requests with 503s while the pool burned CPU on results nobody would read.
        while (queue.length > 0 && abandoned(queue[0])) {
            const dead = queue.shift()!
            dead.pending.reject(new ScrubAbandonedError(`scrub job ${dead.id} was abandoned before it ran`))
        }
        for (const slot of slots) {
            if (!slot?.usable || slot.job || queue.length === 0) {
                continue
            }
            const next = queue.shift()!
            // A worker wedged inside a native ONNX or libvips call answers nothing and cannot be
            // interrupted, so without this the job never settles and the server never releases the
            // concurrency slot it is holding. Armed here, at dispatch, because a deadline armed at
            // enqueue charges queue wait to whichever worker happens to hold the job when it expires:
            // under the overload that causes queueing that destroys healthy workers, which removes
            // capacity and lengthens the queue further.
            const deadline = setTimeout(() => {
                retireAndReplace(slots.indexOf(slot), slot, new Error(`scrub job ${next.id} timed out`))
            }, jobTimeoutMs)
            deadline.unref()
            slot.job = { id: next.id, pending: next.pending, deadline }
            slot.worker.postMessage({ id: next.id, input: next.input })
        }
    }

    /** Nobody is waiting: either the caller hung up, or it has been queued past the point where the
     *  caller's own timeout must already have fired even if we were never told. */
    const abandoned = (job: { signal?: AbortSignal; queuedAt: number }): boolean =>
        job.signal?.aborted === true || performance.now() - job.queuedAt > jobTimeoutMs

    const spawn = async (index: number): Promise<void> => {
        const worker = new Worker(workerUrl, {
            workerData: { ...workerData, index },
            resourceLimits: { maxOldGenerationSizeMb: WORKER_HEAP_MB },
        })
        const slot: Slot = { worker, job: null, usable: false, retired: false, readyAt: 0 }
        slots[index] = slot

        // An 'error' with no listener is rethrown as an uncaught exception, so one worker's failure
        // would take the whole sidecar down. This sink covers the worker's entire life, including
        // the window after the ready race stops listening and before the handlers below are attached.
        worker.on('error', (error) => console.error(`[image-scrub] worker ${index}: ${String(error)}`))

        // Startup failures reject rather than retire, so a worker that cannot load fails startPool
        // instead of respawning forever against whatever is broken. All three exits are covered
        // deliberately: a worker killed while loading models (an OOM, an external terminate) emits
        // `exit` with no `error`, and waiting only on `error` would leave this promise unsettled, so
        // startPool would never resolve, no listener would ever bind, and the pod would sit wedged
        // with nothing logged.
        await new Promise<void>((ready, failed) => {
            const onReady = (msg: ScrubReply): void => {
                if ('ready' in msg) {
                    cleanup()
                    ready()
                }
            }
            const onError = (error: Error): void => {
                cleanup()
                failed(error)
            }
            const onExit = (code: number): void => {
                cleanup()
                failed(new Error(`scrub worker exited with code ${code} before it was ready`))
            }
            const timer = setTimeout(() => {
                cleanup()
                failed(new Error(`scrub worker did not become ready within ${WORKER_READY_TIMEOUT_MS}ms`))
            }, WORKER_READY_TIMEOUT_MS)
            const cleanup = (): void => {
                clearTimeout(timer)
                worker.off('message', onReady)
                worker.off('error', onError)
                worker.off('exit', onExit)
            }
            worker.on('message', onReady)
            worker.once('error', onError)
            worker.once('exit', onExit)
        }).catch((error: unknown) => {
            // Terminate before rethrowing: a worker that timed out is still running, and would go on
            // to finish loading and idle forever holding three ONNX sessions and a thread.
            void worker.terminate().catch(() => {})
            throw error
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
            const { pending, deadline } = slot.job
            clearTimeout(deadline)
            slot.job = null
            // Only a worker that has been up a while counts as recovered. Resetting on the first
            // reply would let a worker that alternates crash and success never accumulate failures,
            // so the backoff below would never engage for exactly the flapping this guards against.
            if (performance.now() - slot.readyAt > RESTART_HEALTHY_MS) {
                restartFailures[index] = 0
            }
            if ('failure' in msg) {
                const error =
                    msg.failure.kind === 'undecodable'
                        ? new UndecodableImageError(msg.failure.message)
                        : msg.failure.kind === 'opt-out'
                          ? new ImageOptOutError(msg.failure.message)
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
        slot.readyAt = performance.now()
        slot.usable = true
    }

    const retireAndReplace = (index: number, slot: Slot, error: Error): void => {
        if (closing || slot.retired) {
            return
        }
        slot.retired = true
        slot.usable = false
        if (slot.job) {
            clearTimeout(slot.job.deadline)
            slot.job.pending.reject(error)
        }
        slot.job = null

        // Replace only once the old worker is actually gone. terminate() cannot interrupt a thread
        // sitting inside a native ONNX or libvips call, and that is precisely the case the job
        // deadline retires a worker for, so spawning on a timer regardless would add a worker while
        // the one it replaces is still holding its isolate, its three sessions and a frame's buffers.
        // A sender able to keep producing images that breach the deadline could then walk the pod
        // past the memory its worker count was sized for, one live-but-retired worker at a time,
        // until it OOMs. Waiting bounds the pool at its configured size: a wedged worker costs its
        // own slot until the native call returns, which is the same capacity it was already failing
        // to provide, and if every slot ends up wedged the liveness probe restarts the pod.
        const terminated = slot.worker.terminate().catch(() => undefined)
        const stillGoing = setTimeout(
            () => console.error(`[image-scrub] worker ${index} has not terminated; its slot stays down until it does`),
            TERMINATE_GRACE_MS
        )
        stillGoing.unref()
        void terminated.then(() => {
            clearTimeout(stillGoing)
            scheduleReplacement(index, error)
        })
    }

    /**
     * Keep trying to rebuild this slot, on a backoff, until one attempt sticks.
     *
     * A replacement that itself fails to start is the same condition as a worker that died, and has
     * to be retried the same way. Giving up after one attempt loses the slot for the process's
     * lifetime: `spawn` writes its slot before it can know the worker is good, so a failed attempt
     * leaves one that is never usable and never retired, which nothing else will ever replace. The
     * pod then serves at reduced capacity indefinitely, and since the liveness probe only fails at
     * zero usable workers nothing restarts it.
     *
     * The backoff exists because a worker that dies on every start (an OOM loading models, a corrupt
     * model file) would otherwise respawn in a tight loop, spending the CPU the survivors need and
     * burying the first failure in log noise.
     */
    const scheduleReplacement = (index: number, error: Error): void => {
        if (closing) {
            return
        }
        ScrubMetrics.incWorkerRestart()
        const failures = (restartFailures[index] ?? 0) + 1
        restartFailures[index] = failures
        const delayMs = Math.min(RESTART_BACKOFF_MAX_MS, RESTART_BACKOFF_BASE_MS * 2 ** (failures - 1))
        console.error(
            `[image-scrub] worker ${index} lost (${failures} in a row), replacing in ${delayMs}ms: ${error.message}`
        )
        const timer = setTimeout(() => {
            if (closing) {
                return
            }
            spawn(index)
                .then(pump)
                .catch((e: unknown) => {
                    ScrubMetrics.incWorkerRestartFailure()
                    scheduleReplacement(index, e instanceof Error ? e : new Error(String(e)))
                })
        }, delayMs)
        timer.unref()
    }

    await Promise.all(Array.from({ length: size }, (_unused, i) => spawn(i)))

    return {
        scrub(input: Buffer, signal?: AbortSignal): Promise<ScrubResult> {
            if (closing) {
                return Promise.reject(new Error('scrub pool is closing'))
            }
            if (signal?.aborted) {
                return Promise.reject(new ScrubAbandonedError('scrub requested by a caller that had already hung up'))
            }
            return new Promise<ScrubResult>((resolve, reject) => {
                queue.push({
                    id: nextJobId++,
                    input,
                    pending: { resolve, reject },
                    signal,
                    queuedAt: performance.now(),
                })
                pump()
            })
        },
        usableWorkers(): number {
            return slots.filter((s) => s?.usable).length
        },
        queueDepth(): number {
            return queue.length
        },
        async close(): Promise<void> {
            closing = true
            for (const pendingJob of queue.splice(0)) {
                pendingJob.pending.reject(new Error('scrub pool is closing'))
            }
            // Slots can be absent while a replacement is still waiting out its backoff.
            for (const slot of slots) {
                if (slot?.job) {
                    clearTimeout(slot.job.deadline)
                    slot.job.pending.reject(new Error('scrub pool is closing'))
                }
            }
            await Promise.all(slots.filter(Boolean).map((s) => s.worker.terminate()))
        },
    }
}
