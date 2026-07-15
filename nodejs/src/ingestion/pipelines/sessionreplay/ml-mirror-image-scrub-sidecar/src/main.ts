import { loadConfig } from './config.ts'
import { ScrubMetrics } from './metrics.ts'
import { advancedScrub, loadModels } from './scrub.ts'
import { startServer } from './server.ts'

const cfg = loadConfig()
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
