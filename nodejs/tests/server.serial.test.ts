// Serial: resets the shared test database and starts a server with shared Kafka/ClickHouse dependencies.
import path from 'path'

import { defaultConfig } from '../src/common/config/config'
import { StallingValkeyProxy } from '../src/common/redis/_tests/stalling-valkey-proxy'
import { PluginServer } from '../src/server'
import { PluginServerMode } from '../src/types'
import { waitForExpect } from './helpers/expectations'
import { ServiceProcess, getFreePort } from './helpers/service-process'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

describe('server', () => {
    jest.retryTimes(3, { logErrorsBeforeRetry: true }) // Flakey due to reliance on kafka/clickhouse
    let pluginsServer: PluginServer | null = null

    beforeEach(async () => {
        jest.spyOn(process, 'exit').mockImplementation()

        await resetTestDatabase()
    })

    afterEach(async () => {
        if (pluginsServer) {
            await pluginsServer.stop()
            expect(process.exit).toHaveBeenCalledTimes(1)
            expect(process.exit).toHaveBeenCalledWith(0)
            pluginsServer = null
        }
    })

    // Ingestion modes are handled by IngestionGeneralServer (see ingestion-general-server.test.ts)
    it('should error on startup with ingestion mode', async () => {
        const server = new PluginServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
        })
        await server.start()
        // start() catches the error and calls stop(error) internally, which exits with 1
        expect(process.exit).toHaveBeenCalledWith(1)
    })

    // Running all capabilities together takes too long in tests, so they are split up
    it('should not error on startup - cdp', async () => {
        pluginsServer = new PluginServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.cdp_processed_events,
            PERSONHOG_ENABLED: true,
            PERSONHOG_ADDR: 'localhost:50052',
        })
        await pluginsServer.start()
    })

    it('keeps batch resolver healthy for the configured audience budget plus processing headroom', async () => {
        pluginsServer = new PluginServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.cdp_cyclotron_worker_batch_resolve,
            PERSONHOG_ENABLED: true,
            PERSONHOG_ADDR: 'localhost:50052',
            CDP_HOG_FLOW_BATCH_AUDIENCE_FETCH_TIMEOUT_MS: 45_000,
        })
        await pluginsServer.start()
        expect(process.exit).not.toHaveBeenCalledWith(1)

        const service = pluginsServer.lifecycle.services.find(({ id }) => id === 'CdpCyclotronWorkerBatchResolve')
        expect(service).toBeDefined()

        const now = Date.now()
        const dateNow = jest.spyOn(Date, 'now')
        try {
            dateNow.mockReturnValue(now + 65_000)
            expect((await service!.healthcheck()).isError()).toBe(false)

            dateNow.mockReturnValue(now + 80_000)
            expect((await service!.healthcheck()).isError()).toBe(true)
        } finally {
            dateNow.mockRestore()
        }
    })

    it('keeps the sandbox email worker process up while its frequency-cap Valkey refuses connections, and healthy once it answers', async () => {
        const frequencyCapValkey = new StallingValkeyProxy({
            host: defaultConfig.CDP_REDIS_HOST,
            port: defaultConfig.CDP_REDIS_PORT,
        })
        const frequencyCapPort = await frequencyCapValkey.start()
        frequencyCapValkey.refuseNewConnections()

        const httpPort = await getFreePort()
        const health = `http://127.0.0.1:${httpPort}/_health`
        const env = { ...process.env }
        delete env.NODE_OPTIONS
        const worker = new ServiceProcess('sandbox-worker', 'pnpm', ['exec', 'tsx', 'src/index.ts'], {
            cwd: path.resolve(__dirname, '..'),
            env: {
                ...env,
                NODE_ENV: 'dev',
                LOG_LEVEL: 'warn',
                REDIS_POOL_MIN_SIZE: '1',
                DATABASE_URL: defaultConfig.DATABASE_URL,
                PERSONS_DATABASE_URL: defaultConfig.PERSONS_DATABASE_URL,
                PERSONS_READONLY_DATABASE_URL: defaultConfig.PERSONS_READONLY_DATABASE_URL,
                BEHAVIORAL_COHORTS_DATABASE_URL: defaultConfig.BEHAVIORAL_COHORTS_DATABASE_URL,
                CYCLOTRON_NODE_DATABASE_URL: defaultConfig.CYCLOTRON_NODE_DATABASE_URL,
                PLUGIN_SERVER_MODE: PluginServerMode.cdp_cyclotron_worker_email_sandbox,
                HTTP_SERVER_PORT: String(httpPort),
                PERSONHOG_ENABLED: 'true',
                PERSONHOG_ADDR: 'localhost:50052',
                OTEL_SDK_DISABLED: 'true',
                CDP_FREQUENCY_CAP_VALKEY_HOST: '127.0.0.1',
                CDP_FREQUENCY_CAP_VALKEY_PORT: String(frequencyCapPort),
            },
        })
        try {
            await waitForExpect(() => {
                expect(frequencyCapValkey.refusedConnections).toBeGreaterThan(10)
            }, 120_000)
            expect(worker.exitInfo()).toBeNull()

            frequencyCapValkey.answerNewConnections()
            await worker.waitForHttpOk(health, 60_000)
            expect(worker.exitInfo()).toBeNull()
        } finally {
            await worker.stop()
            frequencyCapValkey.stop()
        }
    }, 180_000)

    // Replay modes are handled by IngestionSessionReplayServer (see ingestion-session-replay-server.test.ts)
    it('should error on startup with replay mode', async () => {
        const server = new PluginServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.recordings_blob_ingestion_v2,
        })
        await server.start()
        // start() catches the error and calls stop(error) internally, which exits with 1
        expect(process.exit).toHaveBeenCalledWith(1)
    })

    // Logs mode is handled by IngestionLogsServer (see ingestion-logs-server.test.ts)
    it('should error on startup with logs mode', async () => {
        const server = new PluginServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_logs,
        })
        await server.start()
        expect(process.exit).toHaveBeenCalledWith(1)
    })

    // Traces mode is handled by IngestionTracesServer (see ingestion-traces-server.test.ts)
    it('should error on startup with traces mode', async () => {
        const server = new PluginServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_traces,
        })
        await server.start()
        expect(process.exit).toHaveBeenCalledWith(1)
    })
})
