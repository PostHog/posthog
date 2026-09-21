import { Server, createServer } from 'http'

import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresRouterConfig } from '~/common/utils/db/postgres'
import { isProdEnv, isTestEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import { PushCaptureService } from '~/messaging/push-subscriptions/push-capture'
import { createPushSubscriptionsHandler } from '~/messaging/push-subscriptions/push-subscriptions-http'
import { PushSubscriptionsService } from '~/messaging/push-subscriptions/push-subscriptions.service'

import { CommonConfig } from '../common/config'
import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService } from '../types'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

export type PushApiServerConfig = BaseServerConfig &
    PostgresRouterConfig &
    Pick<CommonConfig, 'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'ENCRYPTION_SALT_KEYS' | 'CAPTURE_INTERNAL_URL'> & {
        PUSH_API_PORT: number
        PUSH_API_HOST: string
        /** Django's SECRET_KEY. The rejection log fingerprints a submitted project token with it, so
         * a different value here makes those fingerprints uncorrelatable with the ones Django wrote
         * for the same client. */
        PUSH_API_SECRET_KEY: string
    }

/** Serves `/api/push_subscriptions/`, the endpoint every mobile SDK calls on app open.
 *
 * The registration endpoint listens on its own `node:http` port rather than on the shared express
 * app. `ultimate-express` discards the request body on DELETE, and DELETE with a JSON body is how
 * every released SDK unregisters a device, so serving it there would answer `invalid_json` to every
 * logout. The lifecycle's express app still serves health and metrics on HTTP_SERVER_PORT.
 */
export class PushApiServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: PushApiServerConfig

    private postgres?: PostgresRouter
    private pushServer?: Server
    private listenError?: Error

    constructor(config: Partial<PushApiServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            PUSH_API_PORT: parseInt(process.env.PUSH_API_PORT || '6750', 10),
            PUSH_API_HOST: process.env.PUSH_API_HOST || '0.0.0.0',
            PUSH_API_SECRET_KEY: process.env.SECRET_KEY || '',
            ...config,
        }
        this.lifecycle = new ServerLifecycle(this.config)
    }

    async start(): Promise<void> {
        return this.lifecycle.start(
            () => this.startServices(),
            () => this.getCleanupResources()
        )
    }

    async stop(error?: Error): Promise<void> {
        return this.lifecycle.stop(() => this.getCleanupResources(), error)
    }

    private async startServices(): Promise<void> {
        if (!this.config.PUSH_API_SECRET_KEY && isProdEnv()) {
            // Starting without it would answer requests correctly but write rejection fingerprints
            // that cannot be matched to the ones Django wrote, which is the field used to trace a
            // burst of invalid tokens back to a single misconfigured app.
            throw new Error('SECRET_KEY must be set so rejection fingerprints match the Django endpoint')
        }

        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
        logger.info('👍', 'Postgres Router ready')

        const service = new PushSubscriptionsService(
            new TeamManager(this.postgres),
            this.postgres,
            new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS),
            new PushCaptureService(this.config.CAPTURE_INTERNAL_URL),
            this.config.PUSH_API_SECRET_KEY
        )

        if (!isTestEnv()) {
            this.pushServer = await this.listen(createPushSubscriptionsHandler(service))
        }

        const pluginService: PluginServerService = {
            id: 'push-api',
            onShutdown: async () => {
                await new Promise<void>((resolve) => {
                    if (!this.pushServer) {
                        resolve()
                        return
                    }
                    this.pushServer.close(() => resolve())
                })
            },
            healthcheck: () => this.isHealthy(),
        }
        this.lifecycle.services.push(pluginService)
    }

    private listen(handler: (req: any, res: any) => Promise<void>): Promise<Server> {
        const server = createServer((req, res) => {
            void handler(req, res).catch((error) => {
                // A throw here would otherwise reach the process-level handler and take the pod down
                // over one request, so the connection is answered and the error is left to the logs.
                logger.error('push subscription request failed', { error })
                if (!res.headersSent) {
                    res.writeHead(500, { 'Content-Type': 'application/json' })
                }
                res.end('{"type":"server_error","code":"internal","detail":"Internal error.","attr":null}')
            })
        })

        // A registration is a handful of short fields. Without these a client that opens a connection
        // and sends nothing holds a socket until node's default timeout, which is how a public
        // endpoint is starved of connections rather than of CPU.
        server.headersTimeout = 10_000
        server.requestTimeout = 15_000
        server.keepAliveTimeout = 30_000

        return new Promise((resolve, reject) => {
            server.once('error', (error) => {
                this.listenError = error as Error
                reject(error)
            })
            server.listen(this.config.PUSH_API_PORT, this.config.PUSH_API_HOST, () => {
                logger.info(
                    '🚀',
                    `push subscriptions listening on ${this.config.PUSH_API_HOST}:${this.config.PUSH_API_PORT}`
                )
                resolve(server)
            })
        })
    }

    private isHealthy(): HealthCheckResult {
        if (this.listenError) {
            return new HealthCheckResultError('Push API failed to listen', { error: this.listenError.message })
        }
        if (!isTestEnv() && !this.pushServer?.listening) {
            return new HealthCheckResultError('Push API is not listening', {})
        }
        return new HealthCheckResultOk()
    }

    private getCleanupResources(): CleanupResources {
        return { kafkaProducers: [], redisPools: [], postgres: this.postgres }
    }
}
