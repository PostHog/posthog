import * as Pyroscope from '@pyroscope/nodejs'
import { Server } from 'http'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'
import express from 'ultimate-express'

import { setupCommonRoutes, setupExpressApp } from '../api/router'
import { KafkaProducerWrapper } from '../kafka/producer'
import { onShutdown } from '../lifecycle'
import { PluginServerService, RedisPool } from '../types'
import { PostgresRouter } from '../utils/db/postgres'
import { isTestEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'
import { NodeInstrumentation } from '../utils/node-instrumentation'
import { captureException, shutdown as posthogShutdown } from '../utils/posthog'
import { PubSub } from '../utils/pubsub'
import { delay } from '../utils/utils'

export type BaseServerConfig = {
    INTERNAL_API_SECRET: string
    INSTRUMENT_THREAD_PERFORMANCE: boolean
    HTTP_SERVER_PORT: number
    POD_TERMINATION_ENABLED: boolean
    POD_TERMINATION_BASE_TIMEOUT_MINUTES: number
    POD_TERMINATION_JITTER_MINUTES: number
    CONTINUOUS_PROFILING_ENABLED: boolean
    PYROSCOPE_SERVER_ADDRESS: string
    PYROSCOPE_APPLICATION_NAME: string
}

export interface CleanupResources {
    kafkaProducers: KafkaProducerWrapper[]
    redisPools: RedisPool[]
    postgres?: PostgresRouter
    pubsub?: PubSub
    additionalCleanup?: () => void | Promise<void>
}

/** Minimal interface used by index.ts to interact with any server type. */
export interface NodeServer {
    start(): Promise<void>
    stop(error?: Error): Promise<void>
}

const serverStartupTimeMs = new Counter({
    name: 'plugin_server_startup_time_ms',
    help: 'Time taken to start the nodejs service, in milliseconds',
})

/**
 * Manages the lifecycle concerns shared by all server types: HTTP server,
 * process signals, profiling, pod termination, and graceful shutdown.
 *
 * Concrete servers (PluginServer, IngestionGeneralServer) compose this rather
 * than inheriting from it — they own their domain logic and delegate
 * infrastructure lifecycle here.
 */
export class ServerLifecycle {
    services: PluginServerService[] = []
    httpServer?: Server
    expressApp: express.Application
    stopping = false

    private nodeInstrumentation: NodeInstrumentation
    private podTerminationTimer?: NodeJS.Timeout
    private processListeners: Map<string, (...args: any[]) => void> = new Map()

    constructor(private config: BaseServerConfig) {
        this.expressApp = setupExpressApp({ internalApiSecret: this.config.INTERNAL_API_SECRET })
        this.nodeInstrumentation = new NodeInstrumentation(this.config.INSTRUMENT_THREAD_PERFORMANCE)
        this.setupContinuousProfiling()
    }

    async start(startServices: () => Promise<void>, getCleanupResources: () => CleanupResources): Promise<void> {
        const startupTimer = new Date()
        this.setupListeners(getCleanupResources)
        this.nodeInstrumentation.setupThreadPerformanceInterval()

        try {
            await startServices()

            setupCommonRoutes(this.expressApp, this.services)

            if (!isTestEnv()) {
                this.httpServer = this.expressApp.listen(this.config.HTTP_SERVER_PORT, () => {
                    logger.info('🩺', `HTTP server listening on port ${this.config.HTTP_SERVER_PORT}`)
                })
            }

            serverStartupTimeMs.inc(Date.now() - startupTimer.valueOf())
            logger.info('🚀', `All systems go in ${Date.now() - startupTimer.valueOf()}ms`)

            if (this.config.POD_TERMINATION_ENABLED) {
                this.setupPodTermination(getCleanupResources)
            }
        } catch (error: any) {
            captureException(error)
            logger.error('💥', 'Launchpad failure!', { error: error.stack ?? error })
            logger.error('💥', 'Exception while starting server, shutting down!', { error })
            await this.stop(getCleanupResources, error)
        }
    }

    async stop(getCleanupResources: () => CleanupResources, error?: Error): Promise<void> {
        for (const [event, handler] of this.processListeners) {
            process.removeListener(event, handler)
        }
        this.processListeners.clear()

        if (error) {
            logger.error('🤮', `Shutting down due to error`, { error: error.stack })
        }
        if (this.stopping) {
            logger.info('🚨', 'Stop called but already stopping...')
            return
        }

        this.stopping = true

        if (this.podTerminationTimer) {
            clearTimeout(this.podTerminationTimer)
            this.podTerminationTimer = undefined
        }

        this.nodeInstrumentation.cleanup()

        logger.info('💤', ' Shutting down gracefully...')

        this.httpServer?.close()
        Object.values(schedule.scheduledJobs).forEach((job) => {
            job.cancel()
        })

        const resources = getCleanupResources()

        logger.info('💤', ' Shutting down services...')
        await Promise.allSettled([
            resources.pubsub?.stop(),
            ...this.services.map((s) => s.onShutdown()),
            posthogShutdown(),
            onShutdown(),
        ])

        if (resources.kafkaProducers.length > 0) {
            logger.info('💤', ' Flushing kafka producers...')
            await Promise.all([...resources.kafkaProducers.map((p) => p.flush()), delay(2000)])
        }

        logger.info('💤', ' Shutting down infrastructure...')
        await Promise.allSettled([
            ...resources.kafkaProducers.map((p) => p.disconnect()),
            ...resources.redisPools.map((p) => p.drain()),
            resources.postgres?.end(),
        ])
        for (const pool of resources.redisPools) {
            await pool.clear()
        }
        await resources.additionalCleanup?.()

        logger.info('💤', ' Shutting down completed. Exiting...')

        process.exit(error ? 1 : 0)
    }

    private setupPodTermination(getCleanupResources: () => CleanupResources): void {
        const baseTimeoutMs = this.config.POD_TERMINATION_BASE_TIMEOUT_MINUTES * 60 * 1000
        const jitterMs = Math.random() * this.config.POD_TERMINATION_JITTER_MINUTES * 60 * 1000
        const totalTimeoutMs = baseTimeoutMs + jitterMs

        logger.info('⏰', `Pod termination scheduled in ${Math.round(totalTimeoutMs / 1000 / 60)} minutes`)

        this.podTerminationTimer = setTimeout(() => {
            logger.info('⏰', 'Pod termination timeout reached, shutting down gracefully...')
            void this.stop(getCleanupResources)
        }, totalTimeoutMs)
    }

    private setupListeners(getCleanupResources: () => CleanupResources): void {
        for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
            const handler = async () => {
                logger.info('👋', `process handling ${signal} event. Stopping...`)
                await this.stop(getCleanupResources)
            }
            this.processListeners.set(signal, handler)
            process.on(signal, handler)
        }

        const rejectionHandler = (error: Error | any) => {
            logger.error('🤮', `Unhandled Promise Rejection`, { error: String(error) })

            captureException(error, {
                extra: { detected_at: `ServerLifecycle on unhandledRejection` },
            })

            void this.stop(getCleanupResources, error)
        }
        this.processListeners.set('unhandledRejection', rejectionHandler)
        process.on('unhandledRejection', rejectionHandler)

        const exceptionHandler = async (error: Error) => {
            await this.stop(getCleanupResources, error)
        }
        this.processListeners.set('uncaughtException', exceptionHandler)
        process.on('uncaughtException', exceptionHandler)
    }

    private setupContinuousProfiling(): void {
        if (!this.config.CONTINUOUS_PROFILING_ENABLED) {
            logger.info('Continuous profiling is disabled')
            return
        }

        if (!this.config.PYROSCOPE_SERVER_ADDRESS) {
            logger.warn('Continuous profiling is enabled but PYROSCOPE_SERVER_ADDRESS is empty, skipping')
            return
        }

        try {
            const tags = this.collectK8sTags()

            Pyroscope.init({
                serverAddress: this.config.PYROSCOPE_SERVER_ADDRESS,
                appName: this.config.PYROSCOPE_APPLICATION_NAME || 'nodejs',
                tags,
            })

            Pyroscope.start()
            logger.info('Continuous profiling started', {
                serverAddress: this.config.PYROSCOPE_SERVER_ADDRESS,
                appName: this.config.PYROSCOPE_APPLICATION_NAME || 'nodejs',
                tags,
            })
        } catch (error) {
            logger.error('Failed to start continuous profiling', { error })
        }
    }

    private collectK8sTags(): Record<string, string> {
        const k8sTagEnvVars: Record<string, string> = {
            namespace: 'K8S_NAMESPACE',
            pod: 'K8S_POD_NAME',
            node: 'K8S_NODE_NAME',
            pod_template_hash: 'K8S_POD_TEMPLATE_HASH',
            app_instance: 'K8S_APP_INSTANCE',
            app: 'K8S_APP',
            container: 'K8S_CONTAINER_NAME',
            controller_type: 'K8S_CONTROLLER_TYPE',
        }

        const tags: Record<string, string> = { src: 'SDK' }
        for (const [tagName, envVar] of Object.entries(k8sTagEnvVars)) {
            const value = process.env[envVar]
            if (value) {
                tags[tagName] = value
            } else {
                logger.warn(`K8s tag ${tagName} not set (env var ${envVar} is empty)`)
            }
        }
        return tags
    }
}
