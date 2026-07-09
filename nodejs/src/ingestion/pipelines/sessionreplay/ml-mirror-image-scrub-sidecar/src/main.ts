import { loadConfig } from './config.ts'
import { startServer } from './server.ts'

const cfg = loadConfig()
const { scrub, metrics } = startServer(cfg.port, cfg.metricsPort, cfg.maxConcurrency, cfg.maxBodyBytes)

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
