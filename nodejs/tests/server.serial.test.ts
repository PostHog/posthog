// Serial: resets the shared test database and starts a server with shared Kafka/ClickHouse dependencies.
import { PluginServer } from '../src/server'
import { PluginServerMode } from '../src/types'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

describe('server', () => {
    jest.retryTimes(3) // Flakey due to reliance on kafka/clickhouse
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
