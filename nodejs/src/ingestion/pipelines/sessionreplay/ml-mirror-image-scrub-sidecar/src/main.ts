import { loadConfig } from './config.ts'
import { startServer } from './server.ts'

const cfg = loadConfig()
const server = startServer(cfg.port, cfg.maxConcurrency, cfg.maxBodyBytes)

for (const sig of ['SIGINT', 'SIGTERM'] as const) {
    process.on(sig, () => {
        // Backstop: force-exit before the pod's termination grace period elapses.
        const force = setTimeout(() => process.exit(1), 10_000)
        force.unref()
        server.close(() => {
            clearTimeout(force)
            process.exit(0)
        })
        server.closeIdleConnections()
    })
}
