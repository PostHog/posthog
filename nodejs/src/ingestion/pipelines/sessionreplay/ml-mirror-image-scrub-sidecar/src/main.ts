/* eslint-disable no-console -- sidecar logs to stdout */
import { loadConfig } from './config.ts'
import { ORT_THREADS, SCRUB_WORKERS } from './cores.ts'
import { bindingRatio } from './floors.ts'
import { ScrubMetrics, trackPool } from './metrics.ts'
import { startPool } from './pool.ts'
import { limitsFromEnv } from './scale-plan.ts'
import { startServer } from './server.ts'

// Resolved here rather than in pool.ts: entry points run under tsx, where import.meta works, while
// jest's CJS transform cannot load a src/ module that contains it (see the note in qr.ts).
const WORKER_URL = new URL('./scrub-worker.ts', import.meta.url)

const cfg = loadConfig()
const SCRUB_LIMITS = limitsFromEnv()
// Thread sizing is derived (workers and ORT threads from the cgroup quota) or set outside the process
// (UV_THREADPOOL_SIZE in the Dockerfile), so log what this process actually resolved: a pool sized
// wrong shows up as latency rather than as an error, with no other way to tell from a running pod.
const uvThreadpoolSize = Number(process.env.UV_THREADPOOL_SIZE ?? 4)
console.log(
    `[image-scrub] concurrency=${cfg.maxConcurrency} workers=${SCRUB_WORKERS} ortThreads=${ORT_THREADS} ` +
        `uvThreadpoolSize=${process.env.UV_THREADPOOL_SIZE ?? '4 (libuv default)'} ` +
        `framePixels=${SCRUB_LIMITS.framePixels} storedPixels=${SCRUB_LIMITS.storedPixels} ` +
        `ratio=${(bindingRatio() * SCRUB_LIMITS.safetyFactor).toFixed(2)}x`
)
// The pool is process-wide and every worker's sharp stages queue onto it, so below the worker count
// those stages re-serialise however many workers there are. It cannot be fixed from here: libuv
// builds the pool before any entry-module code runs, so this can only say so.
if (uvThreadpoolSize < SCRUB_WORKERS) {
    console.error(
        `[image-scrub] UV_THREADPOOL_SIZE=${uvThreadpoolSize} is below workers=${SCRUB_WORKERS}, so sharp stages ` +
            `will serialise; raise it in the image and rebuild`
    )
}

// Every worker loads its models before this resolves, so no listener exists until the whole pool can
// scrub and the readiness probe cannot pass on a half-started pool.
const pool = await startPool(SCRUB_WORKERS, WORKER_URL, cfg.jobTimeoutMs)
trackPool(pool)

const { scrub, metrics } = startServer(
    cfg.port,
    cfg.metricsPort,
    cfg.maxConcurrency,
    cfg.maxBodyBytes,
    async (input, signal) => {
        const { out, t } = await pool.scrub(input, signal)
        ScrubMetrics.observeScrubOutcome(t)
        return out
    },
    () => pool.usableWorkers() > 0
)

for (const sig of ['SIGINT', 'SIGTERM'] as const) {
    process.on(sig, () => {
        // Backstop: force-exit before the pod's termination grace period elapses.
        const force = setTimeout(() => process.exit(1), 10_000)
        force.unref()
        let remaining = 2
        const exitWhenBothClosed = (): void => {
            if (--remaining === 0) {
                // The backstop stays armed across pool.close(): terminating a worker wedged inside a
                // native ORT call is exactly the step that can hang, and clearing the timer first
                // would disarm it for the only part of shutdown that needs it.
                void pool.close().finally(() => {
                    clearTimeout(force)
                    process.exit(0)
                })
            }
        }
        for (const server of [scrub, metrics]) {
            server.close(exitWhenBothClosed)
            server.closeIdleConnections()
        }
    })
}
