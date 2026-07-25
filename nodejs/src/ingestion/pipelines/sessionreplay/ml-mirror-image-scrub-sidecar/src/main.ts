import { loadConfig } from './config.ts'

const cfg = loadConfig()
// One libuv thread per in-flight request, because every sharp operation the scrub performs is queued
// onto that pool and a request that cannot get a thread simply waits. libuv sizes the pool the first
// time work is queued onto it and never resizes, so this has to happen before sharp or the ONNX
// binding load. The imports below are dynamic for exactly that reason: static ones are hoisted above
// this line, and import sorting would then decide the ordering on our behalf.
process.env.UV_THREADPOOL_SIZE ??= String(cfg.maxConcurrency)

const { ScrubMetrics } = await import('./metrics.ts')
const { advancedScrub, loadModels } = await import('./scrub.ts')
const { startServer } = await import('./server.ts')

// Models load before any listener exists, so the readiness probe can't pass until the scrub can run.
const models = await loadModels()
const { scrub, metrics } = startServer(
    cfg.port,
    cfg.metricsPort,
    cfg.maxConcurrency,
    cfg.maxBodyBytes,
    async (input) => {
        const { out, t } = await advancedScrub(input, models)
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
                process.exit(0)
            }
        }
        for (const server of [scrub, metrics]) {
            server.close(exitWhenBothClosed)
            server.closeIdleConnections()
        }
    })
}
