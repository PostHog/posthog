import {
    InMemorySessionBus,
    InternalApiClient,
    RedisSessionBus,
    SessionBus,
    SessionQueueManager,
    logger,
} from '@posthog/agent-core'

import { loadConfig } from './config'
import { RevisionResolver } from './resolver'
import { buildServer } from './server'

async function main(): Promise<void> {
    const config = loadConfig()

    const queue = new SessionQueueManager({ pool: { dbUrl: config.queueDbUrl } })
    await queue.connect()

    const apiClient = new InternalApiClient({
        baseUrl: config.internalApiBaseUrl,
        sharedKey: config.internalApiSharedKey,
    })

    const resolver = new RevisionResolver({ client: apiClient, ttlMs: config.resolverTtlMs })

    const bus: SessionBus = config.redisUrl
        ? new RedisSessionBus({ url: config.redisUrl })
        : new InMemorySessionBus()

    if (!config.redisUrl) {
        logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    }

    const app = buildServer({ queue, bus, resolver, domainSuffix: config.domainSuffix })

    const server = app.listen(config.port, () => {
        logger.info('agent-ingress listening', { port: config.port })
    })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-ingress shutting down', { signal })
        server.close()
        await bus.disconnect()
        await queue.disconnect()
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err) => {
    logger.error('agent-ingress fatal', { error: String(err) })
    process.exit(1)
})
