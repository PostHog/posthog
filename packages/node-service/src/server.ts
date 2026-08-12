import { serve, type ServerType } from '@hono/node-server'

import type { NodeService } from './service.js'

export interface StartNodeServiceOptions {
    service: NodeService
    port: number
    hostname?: string
    shutdownGraceMs?: number
    registerProcessHandlers?: boolean
}

export interface StartedNodeService {
    port: number
    server: ServerType
    addShutdownHook(name: string, hook: () => Promise<void> | void): void
    stop(reason?: string): Promise<void>
}

interface ShutdownHook {
    name: string
    hook: () => Promise<void> | void
}

function closeServer(server: ServerType): Promise<void> {
    return new Promise((resolve, reject) => {
        server.close((error) => {
            if (error) {
                reject(error)
                return
            }
            resolve()
        })
    })
}

export async function startNodeService(options: StartNodeServiceOptions): Promise<StartedNodeService> {
    const shutdownHooks: ShutdownHook[] = []
    const shutdownGraceMs = options.shutdownGraceMs ?? 30_000
    let stopPromise: Promise<void> | undefined
    let listeningPort = options.port

    const server = await new Promise<ServerType>((resolve, reject) => {
        const startedServer = serve(
            {
                fetch: options.service.app.fetch,
                hostname: options.hostname ?? '0.0.0.0',
                port: options.port,
            },
            (info) => {
                startedServer.off('error', reject)
                listeningPort = info.port
                resolve(startedServer)
            }
        )
        startedServer.once('error', reject)
    })

    options.service.state.ready = true
    options.service.metrics.serviceReady.set(1)
    options.service.logger.info(
        { event: 'service.started', hostname: options.hostname ?? '0.0.0.0', port: listeningPort },
        'Service started'
    )

    const signalHandlers = new Map<NodeJS.Signals, () => void>()
    const fatalHandlers = new Map<'uncaughtException' | 'unhandledRejection', (error: unknown) => void>()

    const stop = (reason = 'requested'): Promise<void> => {
        if (stopPromise) {
            return stopPromise
        }

        stopPromise = (async () => {
            options.service.state.ready = false
            options.service.state.shuttingDown = true
            options.service.metrics.serviceReady.set(0)
            options.service.metrics.serviceShuttingDown.set(1)
            options.service.logger.info({ event: 'service.stopping', reason }, 'Service stopping')

            for (const [signal, handler] of signalHandlers) {
                process.off(signal, handler)
            }
            for (const [event, handler] of fatalHandlers) {
                process.off(event, handler)
            }

            let drainTimer: NodeJS.Timeout | undefined
            try {
                await Promise.race([
                    closeServer(server),
                    new Promise<never>((_, reject) => {
                        drainTimer = setTimeout(() => reject(new Error('HTTP server drain timed out')), shutdownGraceMs)
                    }),
                ])
            } catch (error) {
                options.service.logger.warn({ event: 'service.drain_timeout', error }, 'HTTP server did not drain')
                if ('closeAllConnections' in server) {
                    server.closeAllConnections()
                }
            } finally {
                if (drainTimer) {
                    clearTimeout(drainTimer)
                }
            }

            for (const { name, hook } of shutdownHooks.toReversed()) {
                try {
                    await hook()
                } catch (error) {
                    options.service.logger.error(
                        { event: 'service.shutdown_hook_failed', hook: name, error },
                        'Shutdown hook failed'
                    )
                }
            }

            options.service.logger.info({ event: 'service.stopped', reason }, 'Service stopped')
        })()

        return stopPromise
    }

    if (options.registerProcessHandlers !== false) {
        for (const signal of ['SIGTERM', 'SIGINT'] as const) {
            const handler = (): void => {
                void stop(signal).finally(() => {
                    process.exitCode = 0
                })
            }
            signalHandlers.set(signal, handler)
            process.on(signal, handler)
        }

        for (const event of ['uncaughtException', 'unhandledRejection'] as const) {
            const handler = (error: unknown): void => {
                options.service.logger.fatal({ event: `service.${event}`, error }, 'Fatal process error')
                void stop(event).finally(() => {
                    process.exitCode = 1
                })
            }
            fatalHandlers.set(event, handler)
            process.on(event, handler)
        }
    }

    return {
        port: listeningPort,
        server,
        addShutdownHook: (name, hook) => {
            shutdownHooks.push({ name, hook })
        },
        stop,
    }
}
