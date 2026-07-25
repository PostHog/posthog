/* eslint-disable no-console -- sidecar logs to stdout */
import { loadConfig } from './config.ts'
import { ORT_THREADS, SCRUB_WORKERS } from './cores.ts'
import { ScrubMetrics } from './metrics.ts'
import { startPool } from './pool.ts'
import { startServer } from './server.ts'

const cfg = loadConfig()
// Thread sizing is derived (workers and ORT threads from the cgroup quota) or set outside the process
// (UV_THREADPOOL_SIZE in the Dockerfile), so log what this process actually resolved: a pool sized
// wrong shows up as latency rather than as an error, with no other way to tell from a running pod.
console.log(
    `[image-scrub] concurrency=${cfg.maxConcurrency} workers=${SCRUB_WORKERS} ortThreads=${ORT_THREADS} ` +
        `uvThreadpoolSize=${process.env.UV_THREADPOOL_SIZE ?? '4 (libuv default)'}`
)

// Every worker loads its models before this resolves, so no listener exists until the whole pool can
// scrub and the readiness probe cannot pass on a half-started pool.
const pool = await startPool(SCRUB_WORKERS)

const { scrub, metrics } = startServer(
    cfg.port,
    cfg.metricsPort,
    cfg.maxConcurrency,
    cfg.maxBodyBytes,
    async (input) => {
        const { out, t } = await pool.scrub(input)
        ScrubMetrics.observeScrubOutcome(t)
        return out
    }
)

for (const sig of ['SIGINT', 'SIGTERM'] as const) {
    process.on(sig, () => {
        // Backstop: force-exit before the pod's termination grace period elapses.
        const force = setTimeout(() => process.exit(1), 10_000)
        force.unref()
        let remaining = 2
        const exitWhenBothClosed = (): void => {
            if (--remaining === 0) {
                clearTimeout(force)
                // Workers hold no unflushed state, so they are torn down after the listeners rather
                // than drained: an in-flight scrub whose socket is already closing has nowhere to go.
                void pool.close().finally(() => process.exit(0))
            }
        }
        for (const server of [scrub, metrics]) {
            server.close(exitWhenBothClosed)
            server.closeIdleConnections()
        }
    })
}
