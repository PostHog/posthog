// Serial: resets the shared test database and starts a server with shared Kafka/ClickHouse dependencies.
import Redis from 'ioredis'

import { defaultConfig } from '../src/common/config/config'
import { StallingValkeyProxy } from '../src/common/redis/_tests/stalling-valkey-proxy'
import { PluginServer } from '../src/server'
import { PluginServerMode } from '../src/types'
import { waitForExpect } from './helpers/expectations'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

describe('server', () => {
    jest.retryTimes(3, { logErrorsBeforeRetry: true }) // Flakey due to reliance on kafka/clickhouse
    let pluginsServer: PluginServer | null = null
    const afterServerStops: (() => void)[] = []

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
        afterServerStops.splice(0).forEach((cleanUp) => cleanUp())
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

    it.each([
        [
            'SES Valkey',
            { host: defaultConfig.CDP_REDIS_HOST, port: defaultConfig.CDP_REDIS_PORT },
            (port: number) => ({
                SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                SES_RATE_LIMITER_VALKEY_PORT: port,
                SES_RATE_LIMITER_VALKEY_PASSWORD: defaultConfig.CDP_REDIS_PASSWORD,
            }),
        ],
        [
            'frequency cap Valkey',
            { host: '127.0.0.1', port: 6390 },
            (port: number) => ({ CDP_FREQUENCY_CAP_VALKEY_HOST: '127.0.0.1', CDP_FREQUENCY_CAP_VALKEY_PORT: port }),
        ],
    ])(
        'keeps the sandbox email worker up while the %s refuses connections, and healthy once it answers',
        async (_name, target, valkeyConfig) => {
            const kill = jest.spyOn(process, 'kill').mockImplementation(() => true)
            const valkey = new StallingValkeyProxy(target)
            const port = await valkey.start()
            afterServerStops.push(() => {
                valkey.stopLeavingClientsSilent()
                kill.mockRestore()
            })
            valkey.refuseNewConnections()
            pluginsServer = new PluginServer({
                LOG_LEVEL: 'debug',
                PLUGIN_SERVER_MODE: PluginServerMode.cdp_cyclotron_worker_email_sandbox,
                PERSONHOG_ENABLED: true,
                PERSONHOG_ADDR: 'localhost:50052',
                ...valkeyConfig(port),
            })
            let serverStarted = false
            const started = pluginsServer.start().then(() => {
                serverStarted = true
            })
            let reference: Redis.Redis | undefined
            try {
                await waitForExpect(() => expect(serverStarted || valkey.refusedConnections > 0).toBe(true), 15_000)

                // A client that stops the process on repeated errors reconnects on this same backoff. This one starts
                // after the worker's pools, so once it has seen more errors than such a client tolerates (10), any
                // such pool in the worker would already have stopped the process.
                let referenceErrors = 0
                reference = new Redis(port, '127.0.0.1')
                reference.on('error', () => {
                    referenceErrors++
                })
                await waitForExpect(() => expect(referenceErrors).toBeGreaterThan(10), 15_000)
                expect(kill).not.toHaveBeenCalled()
            } finally {
                reference?.disconnect()
                valkey.answerNewConnections()
                await started
            }

            const worker = pluginsServer.lifecycle.services.find(({ id }) => id === 'CdpCyclotronWorkerEmailSandbox')
            expect((await worker!.healthcheck()).isError()).toBe(false)
            expect(kill).not.toHaveBeenCalled()
        },
        60_000
    )

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
