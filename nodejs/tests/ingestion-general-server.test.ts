import { PluginServerMode } from '../src/common/config'
import { IngestionGeneralServer } from '../src/servers/ingestion-general-server'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

describe('ingestion general server', () => {
    jest.retryTimes(3) // Flakey due to reliance on kafka/clickhouse
    let server: IngestionGeneralServer | null = null

    beforeEach(async () => {
        jest.spyOn(process, 'exit').mockImplementation()

        await resetTestDatabase()
    })

    afterEach(async () => {
        if (server) {
            await server.stop()
            expect(process.exit).toHaveBeenCalledTimes(1)
            expect(process.exit).toHaveBeenCalledWith(0)
            server = null
        }
    })

    it.each(['analytics', 'ai', 'heatmaps', 'clientwarnings'] as const)(
        'should not error on startup - ingestion_v2 INGESTION_PIPELINE=%s',
        async (pipeline) => {
            server = new IngestionGeneralServer({
                LOG_LEVEL: 'debug',
                PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
                INGESTION_PIPELINE: pipeline,
            })
            await server.start()
            expect(process.exit).not.toHaveBeenCalledWith(1)
        }
    )

    it('should error on startup when ingestion_v2 has no INGESTION_PIPELINE set', async () => {
        // The lifecycle wrapper around start() catches the throw and exits the
        // process with 1 — start() resolves rather than rejecting.
        const localServer = new IngestionGeneralServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
        })
        await localServer.start()
        expect(process.exit).toHaveBeenCalledWith(1)
    })

    it('should not error on startup - ingestion_v2_combined', async () => {
        server = new IngestionGeneralServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2_combined,
        })
        await server.start()
        expect(process.exit).not.toHaveBeenCalledWith(1)
    })
})
